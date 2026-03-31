"""
Motor principal del bot de scalping.
Orquesta todos los componentes: WebSocket, estrategia, ejecución, ML.
"""

import asyncio
from datetime import datetime, timezone, timedelta

from config.settings import (
    BOT_MODE, BotMode, ML_RETRAIN_INTERVAL_HOURS,
    CANDLE_INTERVAL, TEST_INITIAL_BALANCE,
)
from config.pairs import get_all_symbols, get_pair_config
from core.websocket_manager import WebSocketManager
from core.candle_processor import CandleProcessor
from strategy.scalping_strategy import ScalpingStrategy
from strategy.indicators import calculate_all_indicators
from execution.position_manager import PositionManager
from database.supabase_client import db
from ml.predictor import Predictor
from notifications.telegram_notifier import TelegramNotifier
from utils.logger import get_logger
from utils.helpers import seconds_until_candle_close

logger = get_logger(__name__)

# Días de retención de datos
DATA_RETENTION_DAYS = 15


class Engine:
    """
    Orquestador principal del bot.
    """

    def __init__(self):
        self.ws_manager = WebSocketManager()
        self.candle_processor = CandleProcessor()
        self.strategy = ScalpingStrategy()
        self.position_mgr = PositionManager()
        self.predictor = Predictor()
        self.notifier = TelegramNotifier()
        self._running = False
        self._status_interval = 3600
        self._last_prune_date = None  # Para ejecutar pruning 1 vez al día

    async def start(self):
        """Inicia el bot."""
        logger.info(f"═══ SCALPING BOT STARTING ═══ Mode: {BOT_MODE.value}")

        try:
            # ── 1. Inicializar base de datos ──
            db.initialize()
            logger.info("Database initialized")

            # ── 2. Inicializar balance simulado ──
            await self._initialize_balance()

            # ── 3. Inicializar ML ──
            await self.predictor.initialize()
            if self.predictor.is_ready:
                self.strategy.set_ml_predictor(self.predictor)
                logger.info("ML predictor ready")
            else:
                logger.info("ML predictor not ready (collecting data)")

            # ── 4. Cargar historial de velas ──
            await self._load_candle_history()

            # ── 5. Registrar callbacks ──
            self.candle_processor.on_pre_close(self._on_pre_close)
            self.candle_processor.on_close(self._on_candle_close)
            self.ws_manager.on_kline(self.candle_processor.process_kline)
            self.ws_manager.on_ticker(self._on_ticker)

            # ── 6. Notificar inicio ──
            balance = await self._get_balance()
            open_trades = await db.get_open_trades()
            await self.notifier.send_message(
                f"🚀 <b>Bot Scalping iniciado</b>\n"
                f"Modo: {BOT_MODE.value}\n"
                f"Balance: ${balance:.2f}\n"
                f"Posiciones abiertas: {len(open_trades)}\n"
                f"Pares: {', '.join(get_all_symbols())}\n"
                f"ML: {'✅ Ready' if self.predictor.is_ready else '⏳ Collecting data'}"
            )

            # ── 7. Iniciar loops ──
            self._running = True
            await asyncio.gather(
                self.ws_manager.connect(),
                self._status_loop(),
                self._ml_retrain_loop(),
                self._pruning_loop(),
            )

        except Exception as e:
            logger.error(f"Engine error: {e}", exc_info=True)
            await self.notifier.notify_error(str(e))
            raise
        finally:
            await self.shutdown()

    async def _initialize_balance(self):
        """Inicializa el balance virtual para TEST/PAPER."""
        if BOT_MODE == BotMode.LIVE:
            logger.info("Modo LIVE: balance real de Binance")
            return

        state = await db.get_bot_state()

        if state is None:
            logger.info(f"Creando estado inicial: ${TEST_INITIAL_BALANCE:.2f} USDT")
            try:
                db.client.table("futures_bot_state").insert({
                    "total_balance": TEST_INITIAL_BALANCE,
                    "available_balance": TEST_INITIAL_BALANCE,
                    "unrealized_pnl": 0,
                    "daily_pnl": 0, "daily_trades": 0,
                    "daily_wins": 0, "daily_losses": 0,
                    "total_trades": 0, "total_wins": 0, "total_losses": 0,
                    "win_rate": 0, "avg_win": 0, "avg_loss": 0,
                    "profit_factor": 0, "max_drawdown": 0,
                    "samples_collected": 0,
                }).execute()
                logger.info(f"✅ Bot state creado: ${TEST_INITIAL_BALANCE:.2f}")
            except Exception as e:
                logger.error(f"Error creando bot_state: {e}")

        elif float(state.get("total_balance", 0)) == 0:
            logger.info(f"Balance 0. Seteando a ${TEST_INITIAL_BALANCE:.2f}")
            await db.update_bot_state({
                "total_balance": TEST_INITIAL_BALANCE,
                "available_balance": TEST_INITIAL_BALANCE,
            })
        else:
            bal = float(state.get("total_balance", 0))
            logger.info(f"Balance existente: ${bal:.2f} USDT")

    async def shutdown(self):
        """Apaga el bot de forma limpia."""
        logger.info("Shutting down...")
        self._running = False
        await self.ws_manager.disconnect()
        await self.position_mgr.close()
        await self.notifier.send_message("🔴 <b>Bot Scalping detenido</b>")
        await self.notifier.close()
        logger.info("Shutdown complete")

    async def _load_candle_history(self):
        """Carga historial de velas desde Supabase."""
        for symbol in get_all_symbols():
            candles = await db.get_candles(symbol, limit=200)
            if candles:
                self.candle_processor.load_history(symbol, candles)
                logger.info(f"Loaded {len(candles)} candles for {symbol}")
            else:
                logger.info(f"No history for {symbol}, will build from WebSocket")

    # ──────────────────────────────────────────────────────
    # CALLBACKS DE MERCADO
    # ──────────────────────────────────────────────────────

    async def _on_pre_close(self, symbol: str, candle, history: list):
        """
        Pre-cierre de vela (3s antes).
        Genera señales y abre posiciones en TODOS los modos no-LIVE.
        """
        try:
            signal = await self.strategy.analyze(symbol, candle, history)
            if signal is None or signal.signal_type == "NEUTRAL":
                return

            logger.info(
                f"🔔 SIGNAL: {symbol} {signal.signal_type} "
                f"conf={signal.confidence:.2f}"
            )

            # Registrar señal en DB
            await db.insert_signal({
                "symbol": symbol,
                "signal_type": signal.signal_type,
                "confidence": signal.confidence,
                "entry_price": signal.entry_price,
                "suggested_sl": signal.suggested_sl,
                "suggested_tp": signal.suggested_tp,
                "suggested_lev": signal.suggested_leverage,
                "indicators": signal.indicators,
            })

            # ── CAMBIO CLAVE: TEST y PAPER ahora abren posiciones ──
            # En modo LIVE esto también funciona con órdenes reales.
            # La diferencia está en order_manager que simula en TEST/PAPER.
            if BOT_MODE != BotMode.LIVE:
                success = await self.position_mgr.open_position(signal)
                if success:
                    logger.info(
                        f"📈 PAPER TRADE OPENED: {symbol} {signal.signal_type}"
                    )
            else:
                success = await self.position_mgr.open_position(signal)
                if success:
                    logger.info(f"Position opened: {symbol} {signal.signal_type}")

        except Exception as e:
            logger.error(f"Error en pre-close {symbol}: {e}", exc_info=True)

    async def _on_candle_close(self, symbol: str, candle, history: list):
        """
        Cierre confirmado de vela.
        1. Guarda vela en DB con indicadores
        2. Verifica posiciones abiertas contra high/low de la vela
        """
        try:
            logger.info(
                f"📝 Saving candle {symbol} | "
                f"history_len={len(history)} | close={candle.close}"
            )

            # ── Calcular indicadores ──
            all_candles = history
            indicators = (
                calculate_all_indicators(all_candles)
                if len(all_candles) >= 30
                else {}
            )

            # ── Guardar vela ──
            candle_data = candle.to_dict()
            candle_data.update({
                "rsi_14": indicators.get("rsi_14"),
                "ema_9": indicators.get("ema_9"),
                "ema_21": indicators.get("ema_21"),
                "vwap": indicators.get("vwap"),
                "atr_14": indicators.get("atr_14"),
                "volume_sma_20": indicators.get("volume_sma_20"),
                "bb_upper": indicators.get("bb_upper"),
                "bb_lower": indicators.get("bb_lower"),
                "macd": indicators.get("macd"),
                "macd_signal": indicators.get("macd_signal"),
            })
            await db.insert_candle(candle_data)

            # ── Verificar posiciones con high/low de la vela cerrada ──
            # Esto es más preciso que solo usar el close price
            if BOT_MODE != BotMode.LIVE:
                await self.position_mgr.check_positions_candle(
                    symbol=symbol,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                )

        except Exception as e:
            logger.error(f"Error en candle close {symbol}: {e}", exc_info=True)

    async def _on_ticker(self, data: dict):
        """
        Ticker en tiempo real.
        Actualiza trailing stop entre velas.
        """
        try:
            symbol = data.get("s", "")
            current_price = float(data.get("c", 0))
            if current_price > 0:
                await self.position_mgr.check_positions(symbol, current_price)
        except Exception as e:
            logger.error(f"Error en ticker: {e}")

    # ──────────────────────────────────────────────────────
    # LOOPS DE MANTENIMIENTO
    # ──────────────────────────────────────────────────────

    async def _status_loop(self):
        """Envía status periódico por Telegram."""
        while self._running:
            try:
                await asyncio.sleep(self._status_interval)
                if not self._running:
                    break

                state = await db.get_bot_state()
                balance = await self._get_balance()

                if state:
                    await self.notifier.notify_status(
                        balance=balance,
                        daily_pnl=float(state.get("daily_pnl", 0)),
                        daily_trades=int(state.get("daily_trades", 0)),
                        win_rate=float(state.get("win_rate", 0)) * 100,
                        open_positions=len(
                            self.position_mgr.trailing_mgr.get_active_positions()
                        ),
                        mode=BOT_MODE.value,
                    )
            except Exception as e:
                logger.error(f"Error en status loop: {e}")

    async def _ml_retrain_loop(self):
        """Verifica periódicamente si el modelo ML necesita re-entrenarse."""
        while self._running:
            try:
                await asyncio.sleep(3600)
                if not self._running:
                    break

                await self.predictor.maybe_retrain()

                if self.predictor.is_ready and self.strategy.ml_predictor is None:
                    self.strategy.set_ml_predictor(self.predictor)
                    logger.info("ML predictor connected to strategy")

            except Exception as e:
                logger.error(f"Error en ML retrain loop: {e}")

    async def _pruning_loop(self):
        """
        Limpieza diaria de datos antiguos.
        Se ejecuta una vez al día después de medianoche UTC.
        Borra velas, señales y trades con más de DATA_RETENTION_DAYS días.
        """
        while self._running:
            try:
                await asyncio.sleep(300)  # Check cada 5 minutos
                if not self._running:
                    break

                now_utc = datetime.now(timezone.utc)
                today = now_utc.date()

                # Ejecutar solo una vez al día, después de las 00:05 UTC
                if (
                    self._last_prune_date != today
                    and now_utc.hour == 0
                    and now_utc.minute >= 5
                ):
                    self._last_prune_date = today
                    logger.info(
                        f"🧹 Iniciando pruning diario "
                        f"(retención: {DATA_RETENTION_DAYS} días)..."
                    )

                    deleted = await db.prune_old_data(days=DATA_RETENTION_DAYS)

                    logger.info(
                        f"🧹 Pruning completado: "
                        f"candles={deleted.get('candles', 0)} "
                        f"signals={deleted.get('signals', 0)} "
                        f"trades={deleted.get('trades', 0)}"
                    )

                    await self.notifier.send_message(
                        f"🧹 <b>Limpieza diaria completada</b>\n"
                        f"Eliminados datos > {DATA_RETENTION_DAYS} días:\n"
                        f"• Velas: {deleted.get('candles', 0)}\n"
                        f"• Señales: {deleted.get('signals', 0)}\n"
                        f"• Trades cerrados: {deleted.get('trades', 0)}"
                    )

            except Exception as e:
                logger.error(f"Error en pruning loop: {e}")

    async def _get_balance(self) -> float:
        """Obtiene balance según el modo."""
        if BOT_MODE == BotMode.LIVE:
            return await self.position_mgr.order_mgr.get_balance()

        state = await db.get_bot_state()
        if state:
            return float(state.get("total_balance", TEST_INITIAL_BALANCE))
        return TEST_INITIAL_BALANCE
