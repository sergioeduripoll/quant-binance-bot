"""Tests para funciones auxiliares."""

import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helpers import (
    current_timestamp_ms, next_candle_close_ms, seconds_until_candle_close,
    round_price, round_quantity, calculate_pnl, percentage_change,
    format_usdt, format_percentage,
)


class TestTimeFunctions:
    def test_current_timestamp_ms(self):
        ts = current_timestamp_ms()
        assert ts > 1700000000000  # Después de 2023
        assert isinstance(ts, int)

    def test_next_candle_close(self):
        next_close = next_candle_close_ms(300)
        now = current_timestamp_ms()
        assert next_close > now
        assert (next_close - now) <= 300_000

    def test_seconds_until_candle_close(self):
        secs = seconds_until_candle_close(300)
        assert 0 < secs <= 300


class TestRounding:
    def test_round_price(self):
        assert round_price(60123.456789, 2) == 60123.45
        assert round_price(60123.456789, 0) == 60123.0

    def test_round_quantity(self):
        assert round_quantity(0.12345, 3) == 0.123
        assert round_quantity(1.999, 0) == 1.0


class TestPnL:
    def test_long_profit(self):
        pnl = calculate_pnl(60000, 60100, 1.0, "LONG")
        assert pnl == 100.0

    def test_long_loss(self):
        pnl = calculate_pnl(60000, 59900, 1.0, "LONG")
        assert pnl == -100.0

    def test_short_profit(self):
        pnl = calculate_pnl(60000, 59900, 1.0, "SHORT")
        assert pnl == 100.0

    def test_short_loss(self):
        pnl = calculate_pnl(60000, 60100, 1.0, "SHORT")
        assert pnl == -100.0

    def test_small_quantity(self):
        pnl = calculate_pnl(60000, 60100, 0.001, "LONG")
        assert pnl == pytest.approx(0.1)


class TestFormatting:
    def test_format_usdt(self):
        assert format_usdt(1234.56) == "$1,234.56"
        assert format_usdt(0.0012) == "$0.0012"

    def test_format_percentage(self):
        assert format_percentage(5.5) == "+5.50%"
        assert format_percentage(-3.2) == "-3.20%"

    def test_percentage_change(self):
        assert percentage_change(100, 110) == pytest.approx(10.0)
        assert percentage_change(100, 90) == pytest.approx(-10.0)
        assert percentage_change(0, 100) == 0.0
