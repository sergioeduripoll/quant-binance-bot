"""
Modelos de datos / esquemas de tablas.
Documentación de las estructuras usadas en Supabase.
Estos dataclasses sirven como referencia y para validación.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Trade:
    """Esquema de futures_trades."""
    symbol: str
    side: str                          # LONG | SHORT
    entry_price: float
    quantity: float
    leverage: int = 1
    notional_value: float = 0
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # TP | SL | TRAILING_SL | MANUAL
    pnl_gross: float = 0
    commission_paid: float = 0
    pnl_net: float = 0
    pnl_percentage: float = 0
    initial_sl: float = 0
    initial_tp: float = 0
    final_sl: float = 0
    final_tp: float = 0
    risk_reward: float = 0
    status: str = "OPEN"               # OPEN | CLOSED | CANCELLED
    signal_confidence: float = 0
    ml_features: Optional[dict] = None
    entry_order_id: str = ""
    exit_order_id: str = ""
    id: Optional[str] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


@dataclass
class Candle:
    """Esquema de futures_candles."""
    symbol: str
    interval: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0
    trades_count: int = 0
    taker_buy_vol: float = 0
    # Indicadores pre-calculados
    rsi_14: Optional[float] = None
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    vwap: Optional[float] = None
    atr_14: Optional[float] = None
    volume_sma_20: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None


@dataclass
class SignalRecord:
    """Esquema de futures_signals."""
    symbol: str
    signal_type: str                   # LONG | SHORT | NEUTRAL
    confidence: float
    entry_price: Optional[float] = None
    suggested_sl: Optional[float] = None
    suggested_tp: Optional[float] = None
    suggested_lev: Optional[int] = None
    indicators: Optional[dict] = None
    was_executed: bool = False
    trade_id: Optional[str] = None


@dataclass
class BotState:
    """Esquema de futures_bot_state."""
    total_balance: float = 0
    available_balance: float = 0
    unrealized_pnl: float = 0
    daily_pnl: float = 0
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    total_trades: int = 0
    total_wins: int = 0
    total_losses: int = 0
    win_rate: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    profit_factor: float = 0
    max_drawdown: float = 0
    ml_model_version: Optional[str] = None
    ml_accuracy: Optional[float] = None
    ml_last_trained: Optional[datetime] = None
    samples_collected: int = 0


@dataclass
class TrailingEvent:
    """Esquema de futures_trailing_history."""
    trade_id: str
    symbol: str
    old_sl: float
    new_sl: float
    old_tp: float
    new_tp: float
    current_price: float
    current_pnl: float
    reason: str = ""
