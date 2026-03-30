"""
Notificador de Telegram.
Envía alertas de apertura y cierre de operaciones.
"""

import aiohttp
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger
from utils.helpers import format_usdt, format_percentage

logger = get_logger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class TelegramNotifier:
    """Envía notificaciones formateadas a Telegram."""

    def __init__(self):
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send_message(self, text: str, parse_mode: str = "HTML"):
        """Envía mensaje a Telegram."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.debug("Telegram no configurado, skip notificación")
            return

        try:
            session = await self._get_session()
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            async with session.post(
                f"{TELEGRAM_API}/sendMessage", json=payload
            ) as resp:
                if resp.status != 200:
                    data = await resp.json()
                    logger.error(f"Telegram error: {data}")
        except Exception as e:
            logger.error(f"Error enviando Telegram: {e}")

    async def notify_open(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        leverage: int,
        sl: float,
        tp: float,
        confidence: float,
        reasons: list[str],
    ):
        """Notifica apertura de operación."""
        emoji = "🟢" if side == "LONG" else "🔴"
        notional = entry_price * quantity
        reasons_text = "\n".join(f"  • {r}" for r in reasons[:5])

        msg = (
            f"{emoji} <b>NUEVA OPERACIÓN</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Par:</b> {symbol}\n"
            f"<b>Dirección:</b> {side}\n"
            f"<b>Entrada:</b> {format_usdt(entry_price)}\n"
            f"<b>Cantidad:</b> {quantity}\n"
            f"<b>Apalancamiento:</b> {leverage}x\n"
            f"<b>Notional:</b> {format_usdt(notional)}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>🎯 TP:</b> {format_usdt(tp)}\n"
            f"<b>🛑 SL:</b> {format_usdt(sl)}\n"
            f"<b>📊 Confianza:</b> {confidence:.0%}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Razones:</b>\n{reasons_text}"
        )

        await self.send_message(msg)

    async def notify_close(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        leverage: int,
        pnl_gross: float,
        pnl_net: float,
        pnl_pct: float,
        commission: float,
        exit_reason: str,
        trail_count: int = 0,
    ):
        """Notifica cierre de operación."""
        if pnl_net > 0:
            emoji = "✅"
            result = "GANANCIA"
        else:
            emoji = "❌"
            result = "PÉRDIDA"

        reason_map = {
            "TP": "🎯 Take Profit",
            "SL": "🛑 Stop Loss",
            "TRAILING_SL": f"📈 Trailing Stop (×{trail_count})",
            "MANUAL": "✋ Manual",
        }
        reason_text = reason_map.get(exit_reason, exit_reason)

        msg = (
            f"{emoji} <b>OPERACIÓN CERRADA - {result}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Par:</b> {symbol} ({side})\n"
            f"<b>Entrada:</b> {format_usdt(entry_price)}\n"
            f"<b>Salida:</b> {format_usdt(exit_price)}\n"
            f"<b>Razón:</b> {reason_text}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>PnL Bruto:</b> {format_usdt(pnl_gross)}\n"
            f"<b>Comisiones:</b> -{format_usdt(commission)}\n"
            f"<b>PnL Neto:</b> {format_usdt(pnl_net)}\n"
            f"<b>ROI:</b> {format_percentage(pnl_pct)}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Apalancamiento:</b> {leverage}x\n"
            f"<b>Trailing updates:</b> {trail_count}"
        )

        await self.send_message(msg)

    async def notify_status(
        self,
        balance: float,
        daily_pnl: float,
        daily_trades: int,
        win_rate: float,
        open_positions: int,
        mode: str,
    ):
        """Envía resumen de estado del bot."""
        msg = (
            f"📊 <b>STATUS BOT SCALPING</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Modo:</b> {mode}\n"
            f"<b>Balance:</b> {format_usdt(balance)}\n"
            f"<b>PnL Hoy:</b> {format_usdt(daily_pnl)}\n"
            f"<b>Trades Hoy:</b> {daily_trades}\n"
            f"<b>Win Rate:</b> {format_percentage(win_rate)}\n"
            f"<b>Posiciones:</b> {open_positions}\n"
        )
        await self.send_message(msg)

    async def notify_error(self, error_msg: str):
        """Notifica error crítico."""
        msg = f"🚨 <b>ERROR BOT SCALPING</b>\n\n{error_msg}"
        await self.send_message(msg)

    async def notify_ml_trained(
        self, accuracy: float, samples: int, version: str
    ):
        """Notifica entrenamiento de modelo ML."""
        msg = (
            f"🧠 <b>MODELO ML ACTUALIZADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Versión:</b> {version}\n"
            f"<b>Accuracy:</b> {accuracy:.2%}\n"
            f"<b>Muestras:</b> {samples}\n"
        )
        await self.send_message(msg)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
