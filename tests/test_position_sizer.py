"""Tests para el calculador de tamaño de posición."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.position_sizer import PositionSizer


@pytest.fixture
def sizer():
    return PositionSizer()


@pytest.fixture
def pair_config():
    return {
        "symbol": "BTCUSDT",
        "max_leverage": 20,
        "preferred_leverage": 10,
        "qty_precision": 3,
        "price_precision": 2,
    }


class TestPositionSizer:
    def test_basic_sizing(self, sizer, pair_config):
        """Sizing básico con parámetros normales."""
        result = sizer.calculate(
            balance=1000,
            entry_price=60000,
            sl_price=59700,        # $300 de distancia
            tp_price=60600,        # $600 de TP
            side="LONG",
            confidence=0.70,
            pair_config=pair_config,
            open_positions=0,
        )
        assert result is not None
        assert result["quantity"] > 0
        assert result["leverage"] > 0
        assert result["margin_required"] <= 1000 * 0.3  # Max 30%

    def test_risk_limited(self, sizer, pair_config):
        """Riesgo no excede MAX_RISK_PER_TRADE."""
        result = sizer.calculate(
            balance=1000,
            entry_price=60000,
            sl_price=59700,
            tp_price=60600,
            side="LONG",
            confidence=0.70,
            pair_config=pair_config,
        )
        if result:
            # risk_amount debe ser <= 1% del balance
            assert result["risk_amount"] <= 1000 * 0.01 + 0.01

    def test_reduces_size_with_open_positions(self, sizer, pair_config):
        """Reduce tamaño cuando hay posiciones abiertas."""
        result_0 = sizer.calculate(
            balance=1000, entry_price=60000,
            sl_price=59700, tp_price=60600,
            side="LONG", confidence=0.70,
            pair_config=pair_config, open_positions=0,
        )
        result_2 = sizer.calculate(
            balance=1000, entry_price=60000,
            sl_price=59700, tp_price=60600,
            side="LONG", confidence=0.70,
            pair_config=pair_config, open_positions=2,
        )
        if result_0 and result_2:
            assert result_2["quantity"] <= result_0["quantity"]

    def test_rejects_max_positions(self, sizer, pair_config):
        """Rechaza cuando hay máximo de posiciones."""
        result = sizer.calculate(
            balance=1000, entry_price=60000,
            sl_price=59700, tp_price=60600,
            side="LONG", confidence=0.70,
            pair_config=pair_config, open_positions=3,
        )
        assert result is None

    def test_rejects_zero_balance(self, sizer, pair_config):
        """Rechaza con balance 0."""
        result = sizer.calculate(
            balance=0, entry_price=60000,
            sl_price=59700, tp_price=60600,
            side="LONG", confidence=0.70,
            pair_config=pair_config,
        )
        assert result is None

    def test_dynamic_leverage(self, sizer, pair_config):
        """Leverage se ajusta por confianza."""
        lev_high = sizer._dynamic_leverage(0.85, pair_config)
        lev_low = sizer._dynamic_leverage(0.56, pair_config)
        assert lev_high > lev_low

    def test_commission_validation_included(self, sizer, pair_config):
        """El resultado incluye validación de comisiones."""
        result = sizer.calculate(
            balance=1000, entry_price=60000,
            sl_price=59700, tp_price=60600,
            side="LONG", confidence=0.70,
            pair_config=pair_config,
        )
        if result:
            assert "commission_validation" in result
            assert result["commission_validation"]["is_valid"] is True
