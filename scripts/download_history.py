"""
scripts/download_history.py

Descarga las últimas 2000 velas de 5m de cada par desde Binance REST API
y las inserta en futures_candles de Supabase con indicadores pre-calculados.

Uso:
    python scripts/download_history.py
    python scripts/download_history.py --candles 3000
    python scripts/download_history.py --symbols BTCUSDT ETHUSDT

Ejecutar ANTES de cambiar a modo PAPER. No interfiere con el bot corriendo.
"""

import asyncio
import argparse
import sys
import os
import time
import math

import aiohttp
import numpy as np

# Agregar raíz del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import BINANCE_REST_BASE
from config.pairs import get_all_symbols
from database.supabase_client import db
from utils.logger import get_logger

logger = get_logger("download_history")

# ── Binance klines endpoint ──
# Máximo 1500 velas por request
BINANCE_KLINE_LIMIT = 1500
INTERVAL = "5m"


async def fetch_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
    limit: int,
    end_time: int = None,
) -> list[list]:
    """
    Descarga klines de Binance Futures REST API.
    Retorna lista de listas OHLCV.
    """
    url = f"{BINANCE_REST_BASE}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": min(limit, BINANCE_KLINE_LIMIT),
    }
    if end_time:
        params["endTime"] = end_time

    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            logger.error(f"Binance API error {resp.status}: {text}")
            return []
        data = await resp.json()
        return data


async def download_all_candles(
    session: aiohttp.ClientSession,
    symbol: str,
    total_candles: int,
) -> list[dict]:
    """
    Descarga N velas paginando hacia atrás.
    Binance solo permite 1500 por request, así que paginamos.
    """
    all_candles = []
    remaining = total_candles
    end_time = None

    while remaining > 0:
        batch_size = min(remaining, BINANCE_KLINE_LIMIT)
        logger.info(
            f"  {symbol}: Descargando {batch_size} velas "
            f"(faltan {remaining})..."
        )

        raw = await fetch_klines(
            session, symbol, INTERVAL, batch_size, end_time
        )

        if not raw:
            logger.warning(f"  {symbol}: Sin datos en este batch, parando.")
            break

        # Convertir a dict
        for k in raw:
            candle = {
                "symbol": symbol,
                "interval": INTERVAL,
                "open_time": int(k[0]),
                "close_time": int(k[6]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "quote_volume": float(k[7]),
                "trades_count": int(k[8]),
                "taker_buy_vol": float(k[9]),
            }
            all_candles.append(candle)

        # Paginar hacia atrás: usar el open_time de la vela más antigua - 1
        oldest_open = min(c["open_time"] for c in all_candles)
        end_time = oldest_open - 1
        remaining -= len(raw)

        # Rate limit: Binance permite 1200 req/min en futures
        await asyncio.sleep(0.3)

    # Ordenar cronológicamente
    all_candles.sort(key=lambda c: c["open_time"])

    # Eliminar duplicados por open_time
    seen = set()
    unique = []
    for c in all_candles:
        key = c["open_time"]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    logger.info(f"  {symbol}: {len(unique)} velas únicas descargadas")
    return unique


def calculate_indicators_for_batch(candles: list[dict]) -> list[dict]:
    """
    Calcula indicadores técnicos para todo el batch de velas.
    Agrega los campos de indicadores a cada vela.
    """
    if len(candles) < 30:
        return candles

    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])

    # RSI 14
    rsi_vals = _rsi(closes, 14)

    # EMA 9 y 21
    ema_9 = _ema(closes, 9)
    ema_21 = _ema(closes, 21)

    # ATR 14
    atr_vals = _atr(highs, lows, closes, 14)

    # Bollinger Bands 20, 2
    bb_upper, bb_mid, bb_lower = _bollinger(closes, 20, 2.0)

    # MACD
    macd_line, macd_sig, _ = _macd(closes)

    # VWAP
    vwap_vals = _vwap(highs, lows, closes, volumes)

    # Volume SMA 20
    vol_sma = _sma(volumes, 20)

    for i, candle in enumerate(candles):
        candle["rsi_14"] = _safe(rsi_vals[i])
        candle["ema_9"] = _safe(ema_9[i])
        candle["ema_21"] = _safe(ema_21[i])
        candle["atr_14"] = _safe(atr_vals[i])
        candle["bb_upper"] = _safe(bb_upper[i])
        candle["bb_lower"] = _safe(bb_lower[i])
        candle["vwap"] = _safe(vwap_vals[i])
        candle["volume_sma_20"] = _safe(vol_sma[i])
        candle["macd"] = _safe(macd_line[i])
        candle["macd_signal"] = _safe(macd_sig[i])

    return candles


# ── Indicadores (copias locales para independencia del script) ──

def _ema(data, period):
    result = np.full_like(data, np.nan, dtype=float)
    if len(data) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result


def _sma(data, period):
    if len(data) < period:
        return np.full_like(data, np.nan, dtype=float)
    cumsum = np.cumsum(np.insert(data.astype(float), 0, 0))
    result = np.full(len(data), np.nan)
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


def _rsi(closes, period=14):
    result = np.full(len(closes), np.nan)
    if len(closes) < period + 1:
        return result
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            result[i + 1] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return result


def _atr(highs, lows, closes, period=14):
    result = np.full(len(closes), np.nan)
    if len(closes) < period + 1:
        return result
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    atr_v = np.full(len(tr), np.nan)
    atr_v[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr_v[i] = (atr_v[i - 1] * (period - 1) + tr[i]) / period
    result[1:] = atr_v
    return result


def _bollinger(closes, period=20, std_dev=2.0):
    middle = _sma(closes, period)
    std = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        std[i] = np.std(closes[i - period + 1: i + 1])
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def _macd(closes, fast=12, slow=26, signal_period=9):
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _vwap(highs, lows, closes, volumes):
    tp = (highs + lows + closes) / 3
    cum_tp_vol = np.cumsum(tp * volumes)
    cum_vol = np.cumsum(volumes)
    return np.where(cum_vol > 0, cum_tp_vol / cum_vol, np.nan)


def _safe(val):
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return round(float(val), 8)


async def insert_candles_to_supabase(candles: list[dict], symbol: str):
    """
    Inserta velas en Supabase en batches de 100.
    Usa upsert para no duplicar si ya existen.
    """
    BATCH_SIZE = 100
    total = len(candles)
    inserted = 0

    for i in range(0, total, BATCH_SIZE):
        batch = candles[i: i + BATCH_SIZE]
        try:
            result = db.client.table("futures_candles").upsert(
                batch, on_conflict="symbol,open_time"
            ).execute()
            inserted += len(batch)
            logger.info(
                f"  {symbol}: Insertadas {inserted}/{total} velas"
            )
        except Exception as e:
            logger.error(f"  {symbol}: Error insertando batch {i}: {e}")
            # Intentar una por una si falla el batch
            for candle in batch:
                try:
                    db.client.table("futures_candles").upsert(
                        candle, on_conflict="symbol,open_time"
                    ).execute()
                    inserted += 1
                except Exception as e2:
                    logger.error(
                        f"  {symbol}: Error en vela {candle['open_time']}: {e2}"
                    )

        await asyncio.sleep(0.1)  # Gentil con Supabase

    return inserted


async def main():
    parser = argparse.ArgumentParser(
        description="Descarga historial de velas de Binance a Supabase"
    )
    parser.add_argument(
        "--candles", type=int, default=2000,
        help="Cantidad de velas por par (default: 2000)",
    )
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Símbolos específicos (default: todos los configurados)",
    )
    args = parser.parse_args()

    symbols = args.symbols or get_all_symbols()
    total_candles = args.candles

    logger.info("=" * 60)
    logger.info(f"DESCARGA HISTÓRICA DE VELAS")
    logger.info(f"Pares: {', '.join(symbols)}")
    logger.info(f"Velas por par: {total_candles}")
    logger.info(f"Intervalo: {INTERVAL}")
    logger.info(f"Fuente: {BINANCE_REST_BASE}")
    logger.info("=" * 60)

    # Inicializar Supabase
    db.initialize()

    async with aiohttp.ClientSession() as session:
        for symbol in symbols:
            logger.info(f"\n{'─' * 40}")
            logger.info(f"Procesando {symbol}...")

            # 1. Descargar velas de Binance
            candles = await download_all_candles(
                session, symbol, total_candles
            )
            if not candles:
                logger.error(f"  {symbol}: No se pudieron descargar velas")
                continue

            # 2. Calcular indicadores técnicos
            logger.info(f"  {symbol}: Calculando indicadores...")
            candles = calculate_indicators_for_batch(candles)

            # 3. Insertar en Supabase
            logger.info(f"  {symbol}: Insertando en Supabase...")
            inserted = await insert_candles_to_supabase(candles, symbol)
            logger.info(f"  ✅ {symbol}: {inserted} velas insertadas exitosamente")

    # Resumen
    logger.info("\n" + "=" * 60)
    logger.info("DESCARGA COMPLETADA")
    logger.info(f"El bot ahora tiene historial suficiente para:")
    logger.info(f"  - Calcular indicadores desde la primera vela")
    logger.info(f"  - Generar señales inmediatamente")
    logger.info(f"  - Entrenar ML cuando se acumulen trades")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
