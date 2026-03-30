"""
Trailing Stop inteligente basado en estructura de mercado.
Mueve SL y TP dinámicamente según el progreso del trade.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from config.settings import (
    TRAILING_ACTIVATION_RATIO,
    TRAILING_STEP_RATIO,
    TRAILING_TP_EXTENSION_RATIO,
    MIN_PROFIT_AFTER_FEES_RATIO,
    MAKER_FEE,
    TAKER_FEE,
)
from execution.order_manager import OrderManager
from database.supabase_client import db
from utils.logger import get_logger
from utils.helpers import round_price

logger = get_logger(__name__)


@dataclass
class TrailingState:
    """Estado del trailing stop de una posición."""
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    quantity: float
    leverage: int
    current_sl: float
    current_tp: float
    initial_sl: float
    initial_tp: float
    price_precision: int
    trail_count: int = 0
    breakeven_set: bool = False
    last_update_price: float = 0


class TrailingStopManager:
    """
    Gestor de trailing stop inteligente.
    
    Lógica:
    1. Cuando el precio alcanza el 70% del camino al TP:
       - Si la ganancia actual cubre comisiones × MIN_PROFIT_AFTER_FEES_RATIO:
         → Mover SL a entry + ganancia mínima (breakeven+)
         → Extender TP un 50% más
    
    2. Si el precio supera el nuevo TP parcialmente:
       - Repetir el proceso (trail)
       - Cada iteración sube el SL más cerca del precio actual
    
    3. Basado en estructura (ATR), no en % fijos:
       - El step de trailing se adapta a la volatilidad actual
    """

    def __init__(self, order_manager: OrderManager):
        self.order_mgr = order_manager
        self._positions: dict[str, TrailingState] = {}

    def register_position(self, state: TrailingState):
        """Registra una nueva posición para tracking."""
        self._positions[state.trade_id] = state
        logger.info(
            f"Trailing registrado: {state.symbol} {state.side} "
            f"entry={state.entry_price} SL={state.current_sl} TP={state.current_tp}"
        )

    def unregister_position(self, trade_id: str):
        """Elimina posición del tracking."""
        self._positions.pop(trade_id, None)

    async def check_and_update(self, symbol: str, current_price: float, atr: float = None):
        """
        Verifica todas las posiciones del símbolo y actualiza trailing si corresponde.
        Se llama en cada tick o vela.
        """
        for trade_id, state in list(self._positions.items()):
            if state.symbol != symbol:
                continue

            try:
                await self._process_trailing(state, current_price, atr)
            except Exception as e:
                logger.error(f"Error procesando trailing {trade_id}: {e}")

    async def _process_trailing(
        self,
        state: TrailingState,
        current_price: float,
        atr: float = None,
    ):
        """Procesa lógica de trailing para una posición."""
        entry = state.entry_price
        current_sl = state.current_sl
        current_tp = state.current_tp
        side = state.side

        # ── Calcular progreso hacia TP ──
        if side == "LONG":
            total_distance = current_tp - entry
            current_progress = current_price - entry
        else:
            total_distance = entry - current_tp
            current_progress = entry - current_price

        if total_distance <= 0:
            return

        progress_ratio = current_progress / total_distance

        # ── Verificar si activar trailing ──
        if progress_ratio < TRAILING_ACTIVATION_RATIO:
            return

        # ── Calcular ganancia actual vs comisiones ──
        notional = entry * state.quantity
        total_fees = notional * (TAKER_FEE + MAKER_FEE)  # entry taker + exit maker
        current_profit = abs(current_progress) * state.quantity
        min_required_profit = total_fees * MIN_PROFIT_AFTER_FEES_RATIO

        if current_profit < min_required_profit:
            logger.debug(
                f"Trailing {state.symbol}: profit ${current_profit:.4f} < "
                f"min ${min_required_profit:.4f}"
            )
            return

        # ── Evitar actualizar demasiado frecuentemente ──
        if abs(current_price - state.last_update_price) < (atr or total_distance * 0.05) * 0.3:
            return

        # ── Calcular nuevo SL ──
        # Usar ATR si disponible, sino un % del progreso
        trail_step = atr * 0.5 if atr else total_distance * TRAILING_STEP_RATIO

        if side == "LONG":
            # SL mínimo: entry + comisiones cubiertas
            min_sl = entry + (total_fees * MIN_PROFIT_AFTER_FEES_RATIO / state.quantity)
            new_sl = current_price - trail_step
            new_sl = max(new_sl, min_sl)
            # No bajar el SL
            if new_sl <= current_sl:
                return
            # Nuevo TP
            remaining_to_tp = current_tp - current_price
            new_tp = current_tp + (remaining_to_tp * TRAILING_TP_EXTENSION_RATIO)
        else:
            min_sl = entry - (total_fees * MIN_PROFIT_AFTER_FEES_RATIO / state.quantity)
            new_sl = current_price + trail_step
            new_sl = min(new_sl, min_sl)
            if new_sl >= current_sl:
                return
            remaining_to_tp = current_price - current_tp
            new_tp = current_tp - (remaining_to_tp * TRAILING_TP_EXTENSION_RATIO)

        new_sl = round_price(new_sl, state.price_precision)
        new_tp = round_price(new_tp, state.price_precision)

        # ── Ejecutar actualización en Binance ──
        logger.info(
            f"TRAILING {state.symbol} #{state.trail_count + 1}: "
            f"SL {current_sl} → {new_sl} | TP {current_tp} → {new_tp} "
            f"| price={current_price}"
        )

        # Cancelar órdenes SL/TP actuales y colocar nuevas
        await self.order_mgr.cancel_all_orders(state.symbol)

        close_side = "SELL" if side == "LONG" else "BUY"
        await self.order_mgr.stop_loss_order(
            state.symbol, close_side, state.quantity, new_sl
        )
        await self.order_mgr.take_profit_order(
            state.symbol, close_side, state.quantity, new_tp
        )

        # ── Registrar evento ──
        old_sl = state.current_sl
        old_tp = state.current_tp
        state.current_sl = new_sl
        state.current_tp = new_tp
        state.trail_count += 1
        state.last_update_price = current_price
        state.breakeven_set = True

        await db.insert_trailing_event({
            "trade_id": state.trade_id,
            "symbol": state.symbol,
            "old_sl": old_sl,
            "new_sl": new_sl,
            "old_tp": old_tp,
            "new_tp": new_tp,
            "current_price": current_price,
            "current_pnl": current_profit - total_fees,
            "reason": f"Trail #{state.trail_count} progress={progress_ratio:.2f}",
        })

    def get_active_positions(self) -> dict[str, TrailingState]:
        """Retorna posiciones activas."""
        return dict(self._positions)
