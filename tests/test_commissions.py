"""Tests para el calculador de comisiones."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.commission_calc import CommissionCalculator


@pytest.fixture
def calc():
    return CommissionCalculator(maker_fee=0.0002, taker_fee=0.0004)


class TestCommissionCalculator:
    def test_entry_commission_taker(self, calc):
        """Comisión de entrada como taker en BTC."""
        # 1 BTC a $60,000 = $60,000 notional × 0.04% = $24
        fee = calc.entry_commission(60000, 1.0, is_maker=False)
        assert fee == pytest.approx(24.0, rel=1e-4)

    def test_entry_commission_maker(self, calc):
        """Comisión de entrada como maker."""
        # 1 BTC a $60,000 × 0.02% = $12
        fee = calc.entry_commission(60000, 1.0, is_maker=True)
        assert fee == pytest.approx(12.0, rel=1e-4)

    def test_round_trip_fees(self, calc):
        """Comisiones de ida y vuelta."""
        # Entry taker ($24) + Exit maker ($12.02) = ~$36
        total = calc.total_round_trip(
            entry_price=60000, exit_price=60100,
            quantity=1.0,
            entry_maker=False, exit_maker=True,
        )
        assert total == pytest.approx(36.02, rel=1e-3)

    def test_min_profit_target(self, calc):
        """Movimiento mínimo de precio para cubrir comisiones."""
        min_move = calc.min_profit_target(
            entry_price=60000, quantity=0.01, profit_multiple=1.5
        )
        # Worst case fees: 60000 * 0.01 * 0.0004 * 2 = $0.48
        # Min profit: $0.48 * 1.5 = $0.72
        # Min price move: $0.72 / 0.01 = $72
        assert min_move == pytest.approx(72.0, rel=1e-4)

    def test_validate_trade_valid(self, calc):
        """Trade válido: TP suficiente para cubrir comisiones."""
        result = calc.validate_trade(
            entry_price=60000,
            tp_price=60200,
            sl_price=59900,
            quantity=0.01,
            side="LONG",
        )
        assert result["is_valid"] is True
        assert result["net_profit"] > 0
        assert result["fee_to_profit_ratio"] < 0.5

    def test_validate_trade_invalid_small_tp(self, calc):
        """Trade inválido: TP demasiado pequeño."""
        result = calc.validate_trade(
            entry_price=60000,
            tp_price=60005,  # Solo $5 de movimiento
            sl_price=59990,
            quantity=0.001,
            side="LONG",
        )
        # Con qty tan pequeña y movimiento mínimo, fees comen la ganancia
        assert result["fee_to_profit_ratio"] > 0.5 or result["net_profit"] <= 0

    def test_validate_trade_short(self, calc):
        """Trade SHORT válido."""
        result = calc.validate_trade(
            entry_price=60000,
            tp_price=59800,
            sl_price=60100,
            quantity=0.01,
            side="SHORT",
        )
        assert result["is_valid"] is True
        assert result["gross_profit"] > 0


class TestEdgeCases:
    def test_zero_quantity(self, calc):
        """Comisión con cantidad cero."""
        fee = calc.entry_commission(60000, 0, is_maker=False)
        assert fee == 0

    def test_validate_zero_quantity(self, calc):
        """Validación con cantidad cero."""
        result = calc.validate_trade(
            entry_price=60000, tp_price=60100,
            sl_price=59900, quantity=0, side="LONG"
        )
        assert result["is_valid"] is False
