"""
Gestor de conexiones WebSocket a Binance Futures.
Maneja reconexión automática y distribución de datos.
"""

import asyncio
import json
import time
from typing import Callable, Any
import websockets
from websockets.exceptions import ConnectionClosed
from config.settings import BINANCE_WS_BASE, CANDLE_INTERVAL
from config.pairs import get_all_symbols
from utils.logger import get_logger

logger = get_logger(__name__)


class WebSocketManager:
    """Gestiona conexiones WebSocket a Binance Futures."""

    def __init__(self):
        self._ws = None
        self._running = False
        self._callbacks: dict[str, list[Callable]] = {
            "kline": [],
            "ticker": [],
            "depth": [],
        }
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
        self._last_message_time = 0

    def on_kline(self, callback: Callable):
        """Registra callback para datos de velas."""
        self._callbacks["kline"].append(callback)

    def on_ticker(self, callback: Callable):
        """Registra callback para ticker de precio."""
        self._callbacks["ticker"].append(callback)

    def _build_stream_url(self) -> str:
        """Construye la URL del stream combinado."""
        symbols = get_all_symbols()
        streams = []
        for sym in symbols:
            s = sym.lower()
            streams.append(f"{s}@kline_{CANDLE_INTERVAL}")
            streams.append(f"{s}@miniTicker")
        stream_path = "/".join(streams)
        return f"{BINANCE_WS_BASE}/stream?streams={stream_path}"

    async def _dispatch(self, data: dict):
        """Distribuye datos a los callbacks registrados."""
        stream = data.get("stream", "")
        payload = data.get("data", {})

        if "@kline" in stream:
            for cb in self._callbacks["kline"]:
                try:
                    await cb(payload)
                except Exception as e:
                    logger.error(f"Error en callback kline: {e}")

        elif "@miniTicker" in stream:
            for cb in self._callbacks["ticker"]:
                try:
                    await cb(payload)
                except Exception as e:
                    logger.error(f"Error en callback ticker: {e}")

    async def connect(self):
        """Inicia conexión WebSocket con reconexión automática."""
        self._running = True
        url = self._build_stream_url()

        while self._running:
            try:
                logger.info(f"Conectando WebSocket: {len(get_all_symbols())} pares")
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    self._ws = ws
                    self._reconnect_delay = 1
                    logger.info("WebSocket conectado exitosamente")

                    async for message in ws:
                        self._last_message_time = time.time()
                        try:
                            data = json.loads(message)
                            await self._dispatch(data)
                        except json.JSONDecodeError:
                            logger.warning("Mensaje WebSocket no parseable")

            except ConnectionClosed as e:
                logger.warning(f"WebSocket cerrado: {e.code} - {e.reason}")
            except Exception as e:
                logger.error(f"Error WebSocket: {e}")

            if self._running:
                logger.info(
                    f"Reconectando en {self._reconnect_delay}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )

    async def disconnect(self):
        """Cierra la conexión WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
            logger.info("WebSocket desconectado")

    @property
    def is_connected(self) -> bool:
        return (
            self._ws is not None
            and self._ws.open
            and (time.time() - self._last_message_time) < 30
        )
