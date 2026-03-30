"""
Funciones auxiliares compartidas.
"""

import time
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN


def current_timestamp_ms() -> int:
    """Timestamp actual en milisegundos."""
    return int(time.time() * 1000)


def ms_to_datetime(ms: int) -> datetime:
    """Convierte timestamp en ms a datetime UTC."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def next_candle_close_ms(interval_seconds: int = 300) -> int:
    """Calcula el timestamp del próximo cierre de vela."""
    now_ms = current_timestamp_ms()
    interval_ms = interval_seconds * 1000
    return ((now_ms // interval_ms) + 1) * interval_ms


def seconds_until_candle_close(interval_seconds: int = 300) -> float:
    """Segundos hasta el próximo cierre de vela."""
    next_close = next_candle_close_ms(interval_seconds)
    return (next_close - current_timestamp_ms()) / 1000


def round_price(price: float, precision: int) -> float:
    """Redondea precio a la precisión del par."""
    return float(Decimal(str(price)).quantize(
        Decimal(10) ** -precision, rounding=ROUND_DOWN
    ))


def round_quantity(qty: float, precision: int) -> float:
    """Redondea cantidad a la precisión del par."""
    return float(Decimal(str(qty)).quantize(
        Decimal(10) ** -precision, rounding=ROUND_DOWN
    ))


def calculate_pnl(
    entry_price: float,
    exit_price: float,
    quantity: float,
    side: str,
    leverage: int = 1,
) -> float:
    """Calcula P&L bruto de un trade."""
    if side == "LONG":
        return (exit_price - entry_price) * quantity
    else:
        return (entry_price - exit_price) * quantity


def percentage_change(old_val: float, new_val: float) -> float:
    """Calcula cambio porcentual."""
    if old_val == 0:
        return 0.0
    return ((new_val - old_val) / old_val) * 100


def format_usdt(value: float) -> str:
    """Formatea valor en USDT para display."""
    if abs(value) >= 1:
        return f"${value:,.2f}"
    return f"${value:,.4f}"


def format_percentage(value: float) -> str:
    """Formatea porcentaje para display."""
    return f"{value:+.2f}%"
