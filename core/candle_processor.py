"""
Procesador de velas.
Acumula datos de kline, detecta cierres de vela
y dispara el pipeline de análisis en el momento exacto.
"""

import asyncio
import time
from collections import defaultdict
from typing import Callable
from config.settings import CANDLE_SECONDS, CANDLE_PRE_CLOSE_SECONDS
from utils.logger import get_logger
from utils.helpers import current_timestamp_ms

logger = get_logger(__name__)


class CandleData:
    """Representa una vela en construcción o cerrada."""

    __slots__ = [
        "symbol", "interval", "open_time", "close_time",
        "open", "high", "low", "close",
        "volume", "quote_volume", "trades_count",
        "taker_buy_vol", "is_closed",
    ]

    def __init__(self, kline: dict):
        k = kline.get("k", kline)
        self.symbol = k["s"]
        self.interval = k["i"]
        self.open_time = k["t"]
        self.close_time = k["T"]
        self.open = float(k["o"])
        self.high = float(k["h"])
        self.low = float(k["l"])
        self.close = float(k["c"])
        self.volume = float(k["v"])
        self.quote_volume = float(k["q"])
        self.trades_count = int(k["n"])
        self.taker_buy_vol = float(k["V"])
        self.is_closed = k["x"]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "open_time": self.open_time,
            "close_time": self.close_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "quote_volume": self.quote_volume,
            "trades_count": self.trades_count,
            "taker_buy_vol": self.taker_buy_vol,
        }


class CandleProcessor:
    """
    Procesa velas en tiempo real.
    
    Lógica de timing:
    - Acumula datos de cada vela mientras llegan
    - PRE_CLOSE_SECONDS antes del cierre → dispara escaneo pre-cierre
    - Al confirmar cierre de vela → dispara análisis final
    """

    def __init__(self):
        self._current_candles: dict[str, CandleData] = {}
        self._candle_history: dict[str, list[CandleData]] = defaultdict(list)
        self._on_pre_close_callbacks: list[Callable] = []
        self._on_close_callbacks: list[Callable] = []
        self._pre_close_fired: dict[str, int] = {}
        self._history_limit = 250

    def on_pre_close(self, callback: Callable):
        """Registra callback para pre-cierre de vela (3s antes)."""
        self._on_pre_close_callbacks.append(callback)

    def on_close(self, callback: Callable):
        """Registra callback para cierre confirmado de vela."""
        self._on_close_callbacks.append(callback)

    async def process_kline(self, data: dict):
        """
        Procesa un mensaje kline del WebSocket.
        Detecta pre-cierre y cierre de vela.
        """
        candle = CandleData(data)
        symbol = candle.symbol

        # Actualizar vela actual
        self._current_candles[symbol] = candle

        # ── Check pre-cierre ──
        # Disparar escaneo N segundos antes del cierre
        now_ms = current_timestamp_ms()
        pre_close_ms = candle.close_time - (CANDLE_PRE_CLOSE_SECONDS * 1000)
        candle_key = f"{symbol}_{candle.open_time}"

        if (
            now_ms >= pre_close_ms
            and candle_key not in self._pre_close_fired
            and not candle.is_closed
        ):
            self._pre_close_fired[candle_key] = now_ms
            logger.debug(
                f"PRE-CLOSE {symbol} | "
                f"{CANDLE_PRE_CLOSE_SECONDS}s antes del cierre | "
                f"Close: {candle.close}"
            )
            for cb in self._on_pre_close_callbacks:
                try:
                    await cb(symbol, candle, self.get_history(symbol))
                except Exception as e:
                    logger.error(f"Error en pre-close callback {symbol}: {e}")

        # ── Check cierre confirmado ──
        if candle.is_closed:
            logger.debug(
                f"CANDLE CLOSED {symbol} | "
                f"O:{candle.open} H:{candle.high} L:{candle.low} C:{candle.close} "
                f"V:{candle.volume:.0f}"
            )
            # Agregar a historial
            history = self._candle_history[symbol]
            history.append(candle)
            if len(history) > self._history_limit:
                self._candle_history[symbol] = history[-self._history_limit:]

            for cb in self._on_close_callbacks:
                try:
                    await cb(symbol, candle, self.get_history(symbol))
                except Exception as e:
                    logger.error(f"Error en close callback {symbol}: {e}")

            # Limpiar pre-close tracking viejo
            self._cleanup_pre_close_tracking()

    def get_current_price(self, symbol: str) -> float | None:
        """Obtiene el precio actual de un símbolo."""
        candle = self._current_candles.get(symbol)
        return candle.close if candle else None

    def get_history(self, symbol: str) -> list[CandleData]:
        """Obtiene historial de velas cerradas."""
        return list(self._candle_history[symbol])

    def load_history(self, symbol: str, candles: list[dict]):
        """Carga historial desde la base de datos."""
        for c in candles:
            cd = CandleData({"k": {
                "s": symbol, "i": "5m",
                "t": c["open_time"], "T": c["close_time"],
                "o": str(c["open"]), "h": str(c["high"]),
                "l": str(c["low"]), "c": str(c["close"]),
                "v": str(c["volume"]), "q": str(c.get("quote_volume", 0)),
                "n": c.get("trades_count", 0),
                "V": str(c.get("taker_buy_vol", 0)),
                "x": True,
            }})
            self._candle_history[symbol].append(cd)
        logger.info(f"Historial cargado {symbol}: {len(candles)} velas")

    def _cleanup_pre_close_tracking(self):
        """Limpia tracking de pre-close de velas antiguas."""
        now_ms = current_timestamp_ms()
        cutoff = now_ms - (CANDLE_SECONDS * 2 * 1000)
        self._pre_close_fired = {
            k: v for k, v in self._pre_close_fired.items() if v > cutoff
        }
