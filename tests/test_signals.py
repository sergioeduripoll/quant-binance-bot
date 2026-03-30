"""Tests para el generador de señales."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.signal_generator import SignalGenerator, Signal


@pytest.fixture
def generator():
    return SignalGenerator(min_confidence=0.55)


@pytest.fixture
def pair_config():
    return {
        "symbol": "BTCUSDT",
        "max_leverage": 20,
        "preferred_leverage": 10,
        "qty_precision": 3,
        "price_precision": 2,
    }


class TestSignalGenerator:
    def test_strong_long_signal(self, generator, pair_config):
        """Indicadores confluentes alcistas → señal LONG."""
        indicators = {
            "price": 60000,
            "rsi_14": 35,                # Zona de recuperación
            "ema_9": 60100,              # EMA9 > EMA21 (cruce)
            "ema_21": 59900,
            "ema_9_prev": 59800,         # Antes estaba debajo
            "ema_21_prev": 59900,
            "macd": 10,                  # MACD > señal (cruce)
            "macd_signal": -5,
            "macd_prev": -10,
            "macd_signal_prev": -5,
            "macd_histogram": 15,
            "bb_upper": 61000,
            "bb_lower": 59000,
            "bb_mid": 60000,
            "volume_ratio": 1.5,         # Volumen alto
            "stoch_k": 15,               # Cruzando al alza
            "stoch_d": 10,
            "vwap": 59500,               # Precio > VWAP
            "atr_14": 200,
        }
        signal = generator.generate("BTCUSDT", indicators, pair_config)
        assert signal.signal_type == "LONG"
        assert signal.confidence >= 0.55

    def test_strong_short_signal(self, generator, pair_config):
        """Indicadores confluentes bajistas → señal SHORT."""
        indicators = {
            "price": 60000,
            "rsi_14": 68,                # Zona de agotamiento
            "ema_9": 59800,              # EMA9 < EMA21 (cruce bajista)
            "ema_21": 60100,
            "ema_9_prev": 60200,
            "ema_21_prev": 60100,
            "macd": -10,
            "macd_signal": 5,
            "macd_prev": 10,
            "macd_signal_prev": 5,
            "macd_histogram": -15,
            "bb_upper": 60200,
            "bb_lower": 59000,
            "bb_mid": 59600,
            "volume_ratio": 1.8,
            "stoch_k": 85,
            "stoch_d": 90,
            "vwap": 60500,               # Precio < VWAP
            "atr_14": 200,
        }
        signal = generator.generate("BTCUSDT", indicators, pair_config)
        assert signal.signal_type == "SHORT"
        assert signal.confidence >= 0.55

    def test_neutral_when_no_confluence(self, generator, pair_config):
        """Sin confluencia → señal NEUTRAL."""
        indicators = {
            "price": 60000,
            "rsi_14": 50,                # Neutral
            "ema_9": 60000,
            "ema_21": 60000,
            "ema_9_prev": 60000,
            "ema_21_prev": 60000,
            "macd": 0,
            "macd_signal": 0,
            "macd_prev": 0,
            "macd_signal_prev": 0,
            "macd_histogram": 0,
            "bb_upper": 61000,
            "bb_lower": 59000,
            "bb_mid": 60000,
            "volume_ratio": 0.8,         # Volumen bajo
            "stoch_k": 50,
            "stoch_d": 50,
            "vwap": 60000,
            "atr_14": 200,
        }
        signal = generator.generate("BTCUSDT", indicators, pair_config)
        assert signal.signal_type == "NEUTRAL"

    def test_signal_has_sl_tp(self, generator, pair_config):
        """Señal debe tener SL y TP calculados."""
        indicators = {
            "price": 60000,
            "rsi_14": 32,
            "ema_9": 60100, "ema_21": 59900,
            "ema_9_prev": 59800, "ema_21_prev": 59900,
            "macd": 10, "macd_signal": -5,
            "macd_prev": -10, "macd_signal_prev": -5,
            "macd_histogram": 15,
            "bb_upper": 61000, "bb_lower": 59000, "bb_mid": 60000,
            "volume_ratio": 1.5,
            "stoch_k": 15, "stoch_d": 10,
            "vwap": 59500, "atr_14": 200,
        }
        signal = generator.generate("BTCUSDT", indicators, pair_config)
        if signal.signal_type == "LONG":
            assert signal.suggested_sl < signal.entry_price
            assert signal.suggested_tp > signal.entry_price

    def test_leverage_scales_with_confidence(self, generator, pair_config):
        """Mayor confianza → mayor apalancamiento sugerido."""
        lev_high = generator._suggest_leverage(0.85, pair_config)
        lev_med = generator._suggest_leverage(0.70, pair_config)
        lev_low = generator._suggest_leverage(0.58, pair_config)
        assert lev_high >= lev_med >= lev_low

    def test_empty_indicators_returns_neutral(self, generator, pair_config):
        """Indicadores vacíos → NEUTRAL."""
        signal = generator.generate("BTCUSDT", {}, pair_config)
        assert signal.signal_type == "NEUTRAL"
