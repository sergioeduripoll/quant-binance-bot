"""Tests para indicadores técnicos."""

import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.indicators import (
    ema, sma, rsi, atr, bollinger_bands, macd, vwap, stochastic_rsi
)


@pytest.fixture
def sample_closes():
    """100 precios de cierre simulados con tendencia alcista."""
    np.random.seed(42)
    base = np.linspace(100, 110, 100)
    noise = np.random.normal(0, 0.5, 100)
    return base + noise


@pytest.fixture
def sample_ohlcv():
    """OHLCV data simulado."""
    np.random.seed(42)
    closes = np.linspace(100, 110, 100) + np.random.normal(0, 0.5, 100)
    highs = closes + np.abs(np.random.normal(0.3, 0.2, 100))
    lows = closes - np.abs(np.random.normal(0.3, 0.2, 100))
    volumes = np.random.uniform(1000, 5000, 100)
    return highs, lows, closes, volumes


class TestEMA:
    def test_ema_length(self, sample_closes):
        result = ema(sample_closes, 9)
        assert len(result) == len(sample_closes)

    def test_ema_first_values_nan(self, sample_closes):
        result = ema(sample_closes, 9)
        assert np.isnan(result[0])
        assert not np.isnan(result[8])

    def test_ema_tracks_trend(self, sample_closes):
        result = ema(sample_closes, 9)
        # EMA should follow uptrend
        valid = result[~np.isnan(result)]
        assert valid[-1] > valid[0]


class TestSMA:
    def test_sma_basic(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(data, 3)
        assert result[2] == pytest.approx(2.0)
        assert result[4] == pytest.approx(4.0)


class TestRSI:
    def test_rsi_range(self, sample_closes):
        result = rsi(sample_closes, 14)
        valid = result[~np.isnan(result)]
        assert all(0 <= v <= 100 for v in valid)

    def test_rsi_uptrend_above_50(self):
        """RSI de tendencia alcista fuerte debería estar > 50."""
        prices = np.linspace(100, 130, 50)
        result = rsi(prices, 14)
        valid = result[~np.isnan(result)]
        assert valid[-1] > 50


class TestATR:
    def test_atr_positive(self, sample_ohlcv):
        highs, lows, closes, _ = sample_ohlcv
        result = atr(highs, lows, closes, 14)
        valid = result[~np.isnan(result)]
        assert all(v >= 0 for v in valid)


class TestBollingerBands:
    def test_bb_order(self, sample_closes):
        upper, middle, lower = bollinger_bands(sample_closes, 20, 2.0)
        # upper > middle > lower para los valores válidos
        for i in range(19, len(sample_closes)):
            if not np.isnan(upper[i]):
                assert upper[i] >= middle[i] >= lower[i]


class TestMACD:
    def test_macd_shape(self, sample_closes):
        line, signal, hist = macd(sample_closes)
        assert len(line) == len(sample_closes)
        assert len(signal) == len(sample_closes)
        assert len(hist) == len(sample_closes)


class TestStochasticRSI:
    def test_stoch_rsi_range(self, sample_closes):
        k, d = stochastic_rsi(sample_closes)
        valid_k = k[~np.isnan(k)]
        assert all(0 <= v <= 100 for v in valid_k)
