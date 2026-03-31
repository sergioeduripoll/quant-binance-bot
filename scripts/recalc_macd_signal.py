"""
scripts/recalc_macd_signal.py

Recalcula macd_signal para todas las velas existentes en Supabase.
El bug original: la función EMA no manejaba arrays con NaN prefix,
causando que macd_signal quedara NULL en el 100% de las filas.

Uso:
    python scripts/recalc_macd_signal.py

Seguro de correr con el bot activo (solo hace UPDATEs).
"""

import asyncio
import sys
import os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.pairs import get_all_symbols
from database.supabase_client import db
from utils.logger import get_logger

logger = get_logger("recalc_macd")


def ema_fixed(data: np.ndarray, period: int) -> np.ndarray:
    """EMA que maneja NaN prefix correctamente."""
    result = np.full(len(data), np.nan, dtype=float)
    if len(data) < period:
        return result

    k = 2.0 / (period + 1)

    # Encontrar primer tramo de 'period' valores sin NaN
    start = -1
    count = 0
    for i in range(len(data)):
        if not np.isnan(data[i]):
            count += 1
            if count >= period:
                start = i - period + 1
                break
        else:
            count = 0

    if start < 0:
        return result

    seed_idx = start + period - 1
    result[seed_idx] = np.mean(data[start: start + period])

    for i in range(seed_idx + 1, len(data)):
        if np.isnan(data[i]):
            result[i] = result[i - 1]
        else:
            result[i] = data[i] * k + result[i - 1] * (1 - k)

    return result


def safe_float(val):
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return round(float(val), 8)


async def recalculate_symbol(symbol: str):
    """Recalcula macd_signal para un símbolo."""
    logger.info(f"Cargando velas de {symbol}...")

    # Cargar TODAS las velas ordenadas
    result = db.client.table("futures_candles") \
        .select("id,open_time,close,macd") \
        .eq("symbol", symbol) \
        .order("open_time", desc=False) \
        .limit(5000) \
        .execute()

    candles = result.data or []
    if not candles:
        logger.warning(f"  {symbol}: Sin velas")
        return

    logger.info(f"  {symbol}: {len(candles)} velas cargadas")

    # Recalcular MACD completo desde closes
    # Primero necesitamos los closes para recalcular todo
    result2 = db.client.table("futures_candles") \
        .select("id,open_time,open,high,low,close") \
        .eq("symbol", symbol) \
        .order("open_time", desc=False) \
        .limit(5000) \
        .execute()

    rows = result2.data or []
    closes = np.array([float(r["close"]) for r in rows])

    # Calcular MACD con EMA corregida
    ema_fast = ema_fixed(closes, 12)
    ema_slow = ema_fixed(closes, 26)
    macd_line = ema_fast - ema_slow
    macd_signal = ema_fixed(macd_line, 9)

    # Contar cuántos valores válidos hay ahora
    valid_signal = sum(1 for v in macd_signal if not np.isnan(v))
    logger.info(
        f"  {symbol}: macd_signal calculado — "
        f"{valid_signal}/{len(macd_signal)} valores válidos"
    )

    # Actualizar en batches
    BATCH_SIZE = 50
    updated = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch_updates = []
        for j in range(i, min(i + BATCH_SIZE, len(rows))):
            ms = safe_float(macd_signal[j])
            ml = safe_float(macd_line[j])
            if ms is not None:
                batch_updates.append({
                    "id": rows[j]["id"],
                    "macd": ml,
                    "macd_signal": ms,
                })

        if batch_updates:
            for update in batch_updates:
                try:
                    db.client.table("futures_candles") \
                        .update({"macd": update["macd"], "macd_signal": update["macd_signal"]}) \
                        .eq("id", update["id"]) \
                        .execute()
                    updated += 1
                except Exception as e:
                    logger.error(f"  Error update {update['id']}: {e}")

        if (i + BATCH_SIZE) % 200 == 0 or i + BATCH_SIZE >= len(rows):
            logger.info(f"  {symbol}: Actualizadas {updated}/{len(rows)} filas")

    logger.info(f"  ✅ {symbol}: {updated} filas actualizadas con macd_signal")


async def main():
    logger.info("=" * 60)
    logger.info("RECALCULANDO MACD SIGNAL")
    logger.info("Fix: EMA ahora maneja arrays con NaN prefix")
    logger.info("=" * 60)

    db.initialize()
    symbols = get_all_symbols()

    for symbol in symbols:
        await recalculate_symbol(symbol)

    # Verificación final
    logger.info("\n" + "=" * 60)
    logger.info("VERIFICACIÓN")
    for symbol in symbols:
        result = db.client.table("futures_candles") \
            .select("macd_signal", count="exact") \
            .eq("symbol", symbol) \
            .not_.is_("macd_signal", "null") \
            .execute()
        count = result.count or 0
        total = db.client.table("futures_candles") \
            .select("id", count="exact") \
            .eq("symbol", symbol) \
            .execute().count or 0
        logger.info(f"  {symbol}: {count}/{total} filas con macd_signal")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
