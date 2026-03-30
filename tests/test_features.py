"""Tests para ingeniería de features ML."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.feature_engineer import (
    extract_features, features_to_array, create_label, FEATURE_COLUMNS
)


@pytest.fixture
def sample_indicators():
    return {
        "price": 60000,
        "rsi_14": 45,
        "ema_9": 60050,
        "ema_21": 59950,
        "macd_histogram": 5,
        "bb_upper": 61000,
        "bb_lower": 59000,
        "volume_ratio": 1.3,
        "atr_14": 200,
        "stoch_k": 40,
        "stoch_d": 35,
        "vwap": 59800,
    }


class TestFeatureExtraction:
    def test_extract_returns_dict(self, sample_indicators):
        features = extract_features(sample_indicators)
        assert features is not None
        assert isinstance(features, dict)

    def test_all_feature_columns_present(self, sample_indicators):
        features = extract_features(sample_indicators)
        for col in FEATURE_COLUMNS:
            assert col in features, f"Missing feature: {col}"

    def test_rsi_normalized(self, sample_indicators):
        features = extract_features(sample_indicators)
        assert 0 <= features["rsi_14"] <= 1

    def test_bb_position_normalized(self, sample_indicators):
        features = extract_features(sample_indicators)
        assert 0 <= features["bb_position"] <= 1

    def test_volume_ratio_capped(self, sample_indicators):
        sample_indicators["volume_ratio"] = 10.0
        features = extract_features(sample_indicators)
        assert features["volume_ratio"] <= 1.0  # Capped at 5/5

    def test_features_to_array_shape(self, sample_indicators):
        features = extract_features(sample_indicators)
        arr = features_to_array(features)
        assert len(arr) == len(FEATURE_COLUMNS)

    def test_none_price_returns_none(self):
        features = extract_features({"price": None})
        assert features is None

    def test_empty_indicators_returns_none(self):
        features = extract_features({})
        assert features is None


class TestLabels:
    def test_winning_trade_label(self):
        assert create_label({"pnl_net": 10.5}) == 1

    def test_losing_trade_label(self):
        assert create_label({"pnl_net": -5.0}) == 0

    def test_breakeven_trade_label(self):
        assert create_label({"pnl_net": 0}) == 0
