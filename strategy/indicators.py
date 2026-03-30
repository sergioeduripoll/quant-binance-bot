"""
Indicadores técnicos optimizados para scalping.
Calculados sobre arrays de velas para máxima velocidad.
"""

import numpy as np
from typing import Optional


def ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    result = np.full_like(data, np.nan)
    if len(data) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result


def sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    if len(data) < period:
        return np.full_like(data, np.nan)
    cumsum = np.cumsum(np.insert(data, 0, 0))
    result = np.full_like(data, np.nan)
    result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    result = np.full_like(closes, np.nan)
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
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range."""
    result = np.full_like(closes, np.nan)
    if len(closes) < period + 1:
        return result

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    atr_vals = np.full(len(tr), np.nan)
    atr_vals[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period

    result[1:] = atr_vals
    return result


def bollinger_bands(
    closes: np.ndarray, period: int = 20, std_dev: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands: (upper, middle, lower)."""
    middle = sma(closes, period)
    std = np.full_like(closes, np.nan)
    for i in range(period - 1, len(closes)):
        std[i] = np.std(closes[i - period + 1: i + 1])
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD: (macd_line, signal_line, histogram)."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def vwap(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> np.ndarray:
    """Volume Weighted Average Price (intraday reset)."""
    typical_price = (highs + lows + closes) / 3
    cum_tp_vol = np.cumsum(typical_price * volumes)
    cum_vol = np.cumsum(volumes)
    result = np.where(cum_vol > 0, cum_tp_vol / cum_vol, np.nan)
    return result


def volume_profile(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    """Ratio de volumen actual vs SMA de volumen."""
    vol_sma = sma(volumes, period)
    result = np.where(vol_sma > 0, volumes / vol_sma, 1.0)
    return result


def stochastic_rsi(
    closes: np.ndarray,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic RSI: (%K, %D)."""
    rsi_vals = rsi(closes, rsi_period)

    stoch_k = np.full_like(closes, np.nan)
    for i in range(stoch_period - 1, len(rsi_vals)):
        if np.isnan(rsi_vals[i]):
            continue
        window = rsi_vals[i - stoch_period + 1: i + 1]
        window = window[~np.isnan(window)]
        if len(window) == 0:
            continue
        low = np.min(window)
        high = np.max(window)
        if high - low > 0:
            stoch_k[i] = ((rsi_vals[i] - low) / (high - low)) * 100
        else:
            stoch_k[i] = 50.0

    stoch_d = sma(stoch_k, d_period)
    return stoch_k, stoch_d


def calculate_all_indicators(candles: list) -> dict:
    """
    Calcula todos los indicadores para una lista de velas.
    Retorna diccionario con los valores de la última vela.
    """
    if len(candles) < 30:
        return {}

    closes = np.array([c.close for c in candles])
    highs = np.array([c.high for c in candles])
    lows = np.array([c.low for c in candles])
    volumes = np.array([c.volume for c in candles])

    rsi_14 = rsi(closes, 14)
    ema_9 = ema(closes, 9)
    ema_21 = ema(closes, 21)
    atr_14 = atr(highs, lows, closes, 14)
    bb_upper, bb_mid, bb_lower = bollinger_bands(closes, 20, 2.0)
    macd_line, macd_sig, macd_hist = macd(closes)
    vwap_vals = vwap(highs, lows, closes, volumes)
    vol_profile = volume_profile(volumes, 20)
    stoch_k, stoch_d = stochastic_rsi(closes)

    idx = -1  # Última vela

    return {
        "rsi_14": _safe(rsi_14[idx]),
        "ema_9": _safe(ema_9[idx]),
        "ema_21": _safe(ema_21[idx]),
        "atr_14": _safe(atr_14[idx]),
        "bb_upper": _safe(bb_upper[idx]),
        "bb_mid": _safe(bb_mid[idx]),
        "bb_lower": _safe(bb_lower[idx]),
        "macd": _safe(macd_line[idx]),
        "macd_signal": _safe(macd_sig[idx]),
        "macd_histogram": _safe(macd_hist[idx]),
        "vwap": _safe(vwap_vals[idx]),
        "volume_ratio": _safe(vol_profile[idx]),
        "volume_sma_20": _safe(sma(volumes, 20)[idx]),
        "stoch_k": _safe(stoch_k[idx]),
        "stoch_d": _safe(stoch_d[idx]),
        "price": closes[idx],
        "ema_9_prev": _safe(ema_9[idx - 1]),
        "ema_21_prev": _safe(ema_21[idx - 1]),
        "rsi_14_prev": _safe(rsi_14[idx - 1]),
        "macd_prev": _safe(macd_line[idx - 1]),
        "macd_signal_prev": _safe(macd_sig[idx - 1]),
    }


def _safe(val) -> Optional[float]:
    """Convierte NaN a None."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return float(val)
