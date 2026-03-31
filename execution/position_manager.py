"""
Gestor de posiciones.
Coordina apertura/cierre de posiciones con trailing stop y base de datos.
"""

import asyncio
from datetime import datetime, timezone

from config.settings import BOT_MODE, BotMode
from config.pairs import get_pair_config
from execution.order_manager import OrderManager
from execution.trailing_stop import TrailingStopManager, TrailingState
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.commission_calc import CommissionCalculator
from database.supabase_client import db
from notifications.telegram_notifier import TelegramNotifier
from strategy.signal_generator import Signal
from utils.logger import get_logger
from utils.helpers import calculate_pnl, format_usdt

logger = get_logger(__name__)


class PositionManager:
    """Gestiona el ciclo de vida completo de posiciones."""

    def __init__(self):
        self.order_mgr = OrderManager()
        self.position_sizer = PositionSizer()
        self.risk_mgr = RiskManager()
        self.trailing_mgr = TrailingStopManager(self.order_mgr)
        self.commission_calc = CommissionCalculator()
        self.notifier = TelegramNotifier()

    async def open_position(self, signal: Signal) -> bool:
        """
        Abre una posición basada en una señal.
        """
        symbol = signal.symbol
        pair_config = get_pair_config(symbol)
        if not pair_config:
            return False

        # ── 1. Balance y riesgo ──
        balance = await self.order_mgr.get_balance()
        if BOT_MODE != BotMode.LIVE:
            state = await db.get_bot_state()
            balance = float(state.get("total_balance", 100)) if state else 100.0

        risk_check = await self.risk_mgr.can_trade(balance)
        if not risk_check["allowed"]:
            logger.warning(f"Risk check failed: {risk_check['reason']}")
            return False

        open_count = risk_check.get("open_positions", 0)

        # ── 2. Tamaño de posición ──
        sizing = self.position_sizer.calculate(
            balance=balance,
            entry_price=signal.entry_price,
            sl_price=signal.suggested_sl,
            tp_price=signal.suggested_tp,
            side=signal.signal_type,
            confidence=signal.confidence,
            pair_config=pair_config,
            open_positions=open_count,
        )

        if sizing is None:
            logger.warning(f"{symbol}: Sizing rechazado")
            return False

        # ── 3. Ejecutar entrada ──
        result = await self.order_mgr.open_position(
            symbol=symbol,
            side=signal.signal_type,
            quantity=sizing["quantity"],
            leverage=sizing["leverage"],
            sl_price=signal.suggested_sl,
            tp_price=signal.suggested_tp,
            price_precision=pair_config["price_precision"],
        )

        if not result["success"]:
            logger.error(f"Error abriendo {symbol}: {result.get('error')}")
            return False

        # ── 4. Registrar en DB ──
        entry_price = result.get("avg_price", signal.entry_price)
        if entry_price == 0:
            entry_price = signal.entry_price

        trade_data = {
            "symbol": symbol,
            "side": signal.signal_type,
            "entry_price": entry_price,
            "quantity": sizing["quantity"],
            "leverage": sizing["leverage"],
            "notional_value": sizing["notional_value"],
            "initial_sl": signal.suggested_sl,
            "initial_tp": signal.suggested_tp,
            "final_sl": signal.suggested_sl,
            "final_tp": signal.suggested_tp,
            "risk_reward": sizing["commission_validation"].get("risk_reward", 0),
            "signal_confidence": signal.confidence,
            "ml_features": signal.indicators,
            "entry_order_id": result.get("entry_order_id", ""),
            "status": "OPEN",
        }

        trade = await db.insert_trade(trade_data)
        if not trade:
            logger.error(f"Error registrando trade en DB para {symbol}")
            return False

        # ── 5. Configurar trailing stop ──
        trailing_state = TrailingState(
            trade_id=trade["id"],
            symbol=symbol,
            side=signal.signal_type,
            entry_price=entry_price,
            quantity=sizing["quantity"],
            leverage=sizing["leverage"],
            current_sl=signal.suggested_sl,
            current_tp=signal.suggested_tp,
            initial_sl=signal.suggested_sl,
            initial_tp=signal.suggested_tp,
            price_precision=pair_config["price_precision"],
        )
        self.trailing_mgr.register_position(trailing_state)

        # ── 6. Notificar ──
        await self.notifier.notify_open(
            symbol=symbol,
            side=signal.signal_type,
            entry_price=entry_price,
            quantity=sizing["quantity"],
            leverage=sizing["leverage"],
            sl=signal.suggested_sl,
            tp=signal.suggested_tp,
            confidence=signal.confidence,
            reasons=signal.reasons,
            balance=balance,
            margin=sizing["margin_required"],
        )

        logger.info(
            f"📈 POSITION OPENED: {symbol} {signal.signal_type} "
            f"qty={sizing['quantity']} lev={sizing['leverage']}x "
            f"entry={entry_price} SL={signal.suggested_sl} TP={signal.suggested_tp} "
            f"margin=${sizing['margin_required']:.2f}"
        )

        return True

    async def check_positions(self, symbol: str, current_price: float, atr: float = None):
        """
        Verifica posiciones en tiempo real (ticker).
        Solo actualiza trailing, no cierra posiciones.
        Los cierres se hacen en check_positions_candle.
        """
        await self.trailing_mgr.check_and_update(symbol, current_price, atr)

    async def check_positions_candle(
        self,
        symbol: str,
        high: float,
        low: float,
        close: float,
    ):
        """
        Verifica posiciones al cierre de vela usando high/low.

        Más preciso que solo usar close: una vela puede haber
        tocado el SL o TP durante su vida incluso si el close
        está en otro lugar.

        Lógica de prioridad: si una vela toca AMBOS SL y TP,
        se asume que tocó el más cercano al open primero.
        """
        for trade_id, state in list(self.trailing_mgr.get_active_positions().items()):
            if state.symbol != symbol:
                continue

            hit_sl = False
            hit_tp = False

            if state.side == "LONG":
                hit_sl = low <= state.current_sl
                hit_tp = high >= state.current_tp
            else:  # SHORT
                hit_sl = high >= state.current_sl
                hit_tp = low <= state.current_tp

            if hit_sl and hit_tp:
                # Ambos tocados: el más cercano al entry gana
                sl_dist = abs(state.entry_price - state.current_sl)
                tp_dist = abs(state.entry_price - state.current_tp)
                if sl_dist <= tp_dist:
                    hit_tp = False  # SL estaba más cerca
                else:
                    hit_sl = False  # TP estaba más cerca

            if hit_tp:
                await self._close_trade(
                    trade_id=trade_id,
                    state=state,
                    exit_price=state.current_tp,
                    exit_reason="TP",
                )
            elif hit_sl:
                exit_reason = "TRAILING_SL" if state.breakeven_set else "SL"
                await self._close_trade(
                    trade_id=trade_id,
                    state=state,
                    exit_price=state.current_sl,
                    exit_reason=exit_reason,
                )

    async def _simulate_position_check(self, symbol: str, current_price: float):
        """Simula verificación de posiciones con precio actual."""
        for trade_id, state in list(self.trailing_mgr.get_active_positions().items()):
            if state.symbol != symbol:
                continue

            closed = False
            exit_reason = ""
            exit_price = current_price

            if state.side == "LONG":
                if current_price <= state.current_sl:
                    closed = True
                    exit_reason = "TRAILING_SL" if state.breakeven_set else "SL"
                    exit_price = state.current_sl
                elif current_price >= state.current_tp:
                    closed = True
                    exit_reason = "TP"
                    exit_price = state.current_tp
            else:
                if current_price >= state.current_sl:
                    closed = True
                    exit_reason = "TRAILING_SL" if state.breakeven_set else "SL"
                    exit_price = state.current_sl
                elif current_price <= state.current_tp:
                    closed = True
                    exit_reason = "TP"
                    exit_price = state.current_tp

            if closed:
                await self._close_trade(
                    trade_id=trade_id,
                    state=state,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                )

    async def _sync_positions_with_exchange(self, symbol: str):
        """Sincroniza posiciones con Binance en modo LIVE."""
        positions = await self.order_mgr.get_positions()
        position_map = {p["symbol"]: p for p in positions}

        for trade_id, state in list(self.trailing_mgr.get_active_positions().items()):
            if state.symbol != symbol:
                continue

            binance_pos = position_map.get(symbol)
            if binance_pos is None or float(binance_pos.get("positionAmt", 0)) == 0:
                mark_price = (
                    float(binance_pos.get("markPrice", state.entry_price))
                    if binance_pos
                    else state.entry_price
                )
                await self._close_trade(
                    trade_id=trade_id,
                    state=state,
                    exit_price=mark_price,
                    exit_reason="TP",
                )

    async def _close_trade(
        self,
        trade_id: str,
        state: TrailingState,
        exit_price: float,
        exit_reason: str,
    ):
        """Cierra un trade, actualiza wallet y notifica."""
        pnl_gross = calculate_pnl(
            state.entry_price, exit_price, state.quantity, state.side
        )
        commission = self.commission_calc.total_round_trip(
            state.entry_price, exit_price, state.quantity,
            entry_maker=False,
            exit_maker=(exit_reason == "TP"),
        )
        pnl_net = pnl_gross - commission
        pnl_pct = (
            (pnl_net / (state.entry_price * state.quantity))
            * 100
            * state.leverage
        )

        # ── Actualizar trade en DB ──
        await db.update_trade(trade_id, {
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl_gross": pnl_gross,
            "commission_paid": commission,
            "pnl_net": pnl_net,
            "pnl_percentage": pnl_pct,
            "final_sl": state.current_sl,
            "final_tp": state.current_tp,
            "status": "CLOSED",
        })

        # ── Actualizar wallet balance ──
        new_balance = await db.update_wallet_balance(pnl_net)

        # ── Actualizar riesgo en memoria ──
        self.risk_mgr.update_daily_pnl(pnl_net)

        # ── Remover del trailing ──
        self.trailing_mgr.unregister_position(trade_id)

        # ── Notificar con saldo actualizado ──
        await self.notifier.notify_close(
            symbol=state.symbol,
            side=state.side,
            entry_price=state.entry_price,
            exit_price=exit_price,
            quantity=state.quantity,
            leverage=state.leverage,
            pnl_gross=pnl_gross,
            pnl_net=pnl_net,
            pnl_pct=pnl_pct,
            commission=commission,
            exit_reason=exit_reason,
            trail_count=state.trail_count,
            new_balance=new_balance,
        )

        emoji = "✅" if pnl_net > 0 else "❌"
        logger.info(
            f"{emoji} POSITION CLOSED: {state.symbol} {state.side} "
            f"entry={state.entry_price} exit={exit_price} "
            f"PnL={format_usdt(pnl_net)} ({pnl_pct:+.2f}%) "
            f"reason={exit_reason} trails={state.trail_count} "
            f"balance=${new_balance:.2f}"
        )

    async def close(self):
        """Limpieza al apagar el bot."""
        await self.order_mgr.close()
