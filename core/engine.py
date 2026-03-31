"""
Motor principal del bot de scalping.
Orquesta todos los componentes: WebSocket, estrategia, ejecución, ML.
"""

import asyncio
from datetime import datetime, timezone

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


class Engine:
    """
    Orquestador principal del bot.
    
    Ciclo de vida:
    1. Inicialización: DB, ML, WebSocket
    2. Recepción de datos via WebSocket
    3. Pre-close: análisis y generación de señales
    4. Ejecución: apertura de posiciones
    5. Monitoreo: trailing stop, cierre de posiciones
    6. ML: re-entrenamiento periódico
    """

    def __init__(self):
        self.ws_manager = WebSocketManager()
        self.candle_processor = CandleProcessor()
        self.strategy = ScalpingStrategy()
        self.position_mgr = PositionManager()
        self.predictor = Predictor()
        self.notifier = TelegramNotifier()
        self._running = False
        self._status_interval = 3600  # Status cada 1 hora

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
            await self.notifier.send_message(
                f"🚀 <b>Bot Scalping iniciado</b>\n"
                f"Modo: {BOT_MODE.value}\n"
                f"Balance: ${balance:.2f}\n"
                f"Pares: {', '.join(get_all_symbols())}\n"
                f"ML: {'✅ Ready' if self.predictor.is_ready else '⏳ Collecting data'}"
            )

            # ── 7. Iniciar loops ──
            self._running = True
            await asyncio.gather(
                self.ws_manager.connect(),
                self._status_loop(),
                self._ml_retrain_loop(),
            )

        except Exception as e:
            logger.error(f"Engine error: {e}", exc_info=True)
            await self.notifier.notify_error(str(e))
            raise
        finally:
            await self.shutdown()

    async def _initialize_balance(self):
        """
        Inicializa el balance virtual para TEST/PAPER.
        
        Si futures_bot_state no tiene registro o tiene balance 0,
        lo crea/actualiza con TEST_INITIAL_BALANCE.
        Solo aplica en modos TEST y PAPER.
        """
        if BOT_MODE == BotMode.LIVE:
            logger.info("Modo LIVE: balance real de Binance")
            return

        state = await db.get_bot_state()

        if state is None:
            # No existe registro → crear con balance inicial
            logger.info(
                f"Creando estado inicial: ${TEST_INITIAL_BALANCE:.2f} USDT"
            )
            try:
                db.client.table("futures_bot_state").insert({
                    "total_balance": TEST_INITIAL_BALANCE,
                    "available_balance": TEST_INITIAL_BALANCE,
                    "unrealized_pnl": 0,
                    "daily_pnl": 0,
                    "daily_trades": 0,
                    "daily_wins": 0,
                    "daily_losses": 0,
                    "total_trades": 0,
                    "total_wins": 0,
                    "total_losses": 0,
                    "win_rate": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_factor": 0,
                    "max_drawdown": 0,
                    "samples_collected": 0,
                }).execute()
                logger.info(f"✅ Bot state creado: ${TEST_INITIAL_BALANCE:.2f}")
            except Exception as e:
                logger.error(f"Error creando bot_state: {e}")

        elif float(state.get("total_balance", 0)) == 0:
            # Existe pero balance es 0 → actualizar
            logger.info(
                f"Balance actual: $0. Seteando a ${TEST_INITIAL_BALANCE:.2f}"
            )
            await db.update_bot_state({
                "total_balance": TEST_INITIAL_BALANCE,
                "available_balance": TEST_INITIAL_BALANCE,
            })
            logger.info(f"✅ Balance actualizado: ${TEST_INITIAL_BALANCE:.2f}")

        else:
            current = float(state.get("total_balance", 0))
            logger.info(
                f"Balance existente: ${current:.2f} USDT "
                f"(no se resetea automáticamente)"
            )

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

    async def _on_pre_close(self, symbol: str, candle, history: list):
        """
        Callback de pre-cierre de vela (3s antes).
        Aquí se ejecuta el análisis y la decisión de trading.
        """
        try:
            # ── Analizar ──
            signal = await self.strategy.analyze(symbol, candle, history)
            if signal is None or signal.signal_type == "NEUTRAL":
                return

            logger.info(
                f"SIGNAL: {symbol} {signal.signal_type} "
                f"conf={signal.confidence:.2f}"
            )

            # ── Registrar señal en DB ──
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

            # ── Ejecutar si el modo lo permite ──
            if BOT_MODE in (BotMode.PAPER, BotMode.LIVE):
                success = await self.position_mgr.open_position(signal)
                if success:
                    logger.info(f"Position opened: {symbol} {signal.signal_type}")
            elif BOT_MODE == BotMode.TEST:
                # En modo TEST solo recolectamos datos
                logger.info(
                    f"[TEST] Signal recorded: {symbol} {signal.signal_type} "
                    f"conf={signal.confidence:.2f}"
                )

        except Exception as e:
            logger.error(f"Error en pre-close {symbol}: {e}", exc_info=True)

    async def _on_candle_close(self, symbol: str, candle, history: list):
        """
        Callback de cierre confirmado de vela.
        Guarda vela en DB y actualiza indicadores.
        """
        try:
            logger.info(
                f"📝 Saving candle {symbol} | "
                f"history_len={len(history)} | close={candle.close}"
            )

            # Calcular indicadores para la vela cerrada
            all_candles = history  # ya incluye la vela cerrada
            indicators = calculate_all_indicators(all_candles) if len(all_candles) >= 30 else {}

            # Guardar vela con indicadores
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

        except Exception as e:
            logger.error(f"Error en candle close {symbol}: {e}", exc_info=True)

    async def _on_ticker(self, data: dict):
        """
        Callback de ticker (actualización de precio en tiempo real).
        Usado para monitorear trailing stop entre velas.
        """
        try:
            symbol = data.get("s", "")
            current_price = float(data.get("c", 0))
            if current_price > 0:
                await self.position_mgr.check_positions(symbol, current_price)
        except Exception as e:
            logger.error(f"Error en ticker: {e}")

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
                await asyncio.sleep(3600)  # Check cada hora
                if not self._running:
                    break

                await self.predictor.maybe_retrain()

                if self.predictor.is_ready and self.strategy.ml_predictor is None:
                    self.strategy.set_ml_predictor(self.predictor)
                    logger.info("ML predictor connected to strategy")

            except Exception as e:
                logger.error(f"Error en ML retrain loop: {e}")

    async def _get_balance(self) -> float:
        """
        Obtiene balance según el modo.
        
        - LIVE: balance real de Binance API
        - TEST/PAPER: balance virtual de futures_bot_state
        """
        if BOT_MODE == BotMode.LIVE:
            return await self.position_mgr.order_mgr.get_balance()

        state = await db.get_bot_state()
        if state:
            return float(state.get("total_balance", TEST_INITIAL_BALANCE))
        return TEST_INITIAL_BALANCE
