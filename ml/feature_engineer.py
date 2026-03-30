"""
Ingeniería de features para el modelo ML.
Transforma indicadores en features normalizados para entrenamiento/predicción.
"""

import numpy as np
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)

# Features que usamos para el modelo
FEATURE_COLUMNS = [
    "rsi_14",
    "ema_9_distance",      # distancia precio-EMA9 normalizada
    "ema_21_distance",     # distancia precio-EMA21 normalizada
    "ema_cross_signal",    # 1 si EMA9 > EMA21, -1 si no
    "macd_histogram",
    "bb_position",         # posición relativa en Bollinger (0-1)
    "bb_width",            # ancho relativo de Bollinger
    "volume_ratio",
    "atr_normalized",      # ATR como % del precio
    "stoch_k",
    "stoch_d",
    "price_change_1",      # cambio % última vela
    "price_change_3",      # cambio % últimas 3 velas
    "volume_change_1",     # cambio % volumen última vela
    "taker_buy_ratio",     # ratio de compra/venta
    "candle_body_ratio",   # ratio cuerpo/sombra de la vela
    "upper_shadow_ratio",
    "lower_shadow_ratio",
]


def extract_features(indicators: dict, candles: list = None) -> Optional[dict]:
    """
    Extrae features normalizados del diccionario de indicadores.
    
    Args:
        indicators: diccionario con valores de indicadores
        candles: lista de velas recientes para features adicionales
    
    Returns:
        dict con features normalizados o None si datos insuficientes
    """
    try:
        price = indicators.get("price")
        if price is None or price == 0:
            return None

        features = {}

        # RSI normalizado a [0, 1]
        rsi = indicators.get("rsi_14")
        features["rsi_14"] = rsi / 100 if rsi is not None else 0.5

        # Distancia precio-EMA normalizada
        ema9 = indicators.get("ema_9")
        ema21 = indicators.get("ema_21")
        features["ema_9_distance"] = (price - ema9) / price if ema9 else 0
        features["ema_21_distance"] = (price - ema21) / price if ema21 else 0

        # EMA cross signal
        features["ema_cross_signal"] = 1 if (ema9 and ema21 and ema9 > ema21) else -1

        # MACD histogram normalizado
        macd_hist = indicators.get("macd_histogram")
        features["macd_histogram"] = (macd_hist / price) if macd_hist else 0

        # Bollinger position [0, 1]
        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")
        if bb_upper and bb_lower and (bb_upper - bb_lower) > 0:
            features["bb_position"] = (price - bb_lower) / (bb_upper - bb_lower)
            features["bb_width"] = (bb_upper - bb_lower) / price
        else:
            features["bb_position"] = 0.5
            features["bb_width"] = 0

        # Volume ratio
        features["volume_ratio"] = min(indicators.get("volume_ratio", 1.0), 5.0) / 5.0

        # ATR normalizado
        atr = indicators.get("atr_14")
        features["atr_normalized"] = (atr / price) if atr else 0

        # Stochastic RSI normalizado
        features["stoch_k"] = (indicators.get("stoch_k", 50) or 50) / 100
        features["stoch_d"] = (indicators.get("stoch_d", 50) or 50) / 100

        # Features de velas (si hay historial)
        if candles and len(candles) >= 3:
            last = candles[-1]
            prev = candles[-2]
            prev3 = candles[-4] if len(candles) >= 4 else candles[-3]

            features["price_change_1"] = (last.close - prev.close) / prev.close if prev.close > 0 else 0
            features["price_change_3"] = (last.close - prev3.close) / prev3.close if prev3.close > 0 else 0
            features["volume_change_1"] = (
                (last.volume - prev.volume) / prev.volume if prev.volume > 0 else 0
            )

            total_vol = last.volume
            features["taker_buy_ratio"] = last.taker_buy_vol / total_vol if total_vol > 0 else 0.5

            candle_range = last.high - last.low
            if candle_range > 0:
                body = abs(last.close - last.open)
                features["candle_body_ratio"] = body / candle_range
                upper_shadow = last.high - max(last.close, last.open)
                lower_shadow = min(last.close, last.open) - last.low
                features["upper_shadow_ratio"] = upper_shadow / candle_range
                features["lower_shadow_ratio"] = lower_shadow / candle_range
            else:
                features["candle_body_ratio"] = 0
                features["upper_shadow_ratio"] = 0
                features["lower_shadow_ratio"] = 0
        else:
            features["price_change_1"] = 0
            features["price_change_3"] = 0
            features["volume_change_1"] = 0
            features["taker_buy_ratio"] = 0.5
            features["candle_body_ratio"] = 0
            features["upper_shadow_ratio"] = 0
            features["lower_shadow_ratio"] = 0

        # Clamp valores extremos
        for key in features:
            val = features[key]
            if isinstance(val, (int, float)):
                features[key] = max(-10, min(10, val))

        return features

    except Exception as e:
        logger.error(f"Error extrayendo features: {e}")
        return None


def features_to_array(features: dict) -> np.ndarray:
    """Convierte dict de features a array numpy ordenado."""
    return np.array([features.get(col, 0) for col in FEATURE_COLUMNS])


def create_label(trade: dict) -> int:
    """
    Crea label para entrenamiento supervisado.
    1 = trade rentable (pnl_net > 0)
    0 = trade no rentable
    """
    pnl_net = float(trade.get("pnl_net", 0))
    return 1 if pnl_net > 0 else 0
