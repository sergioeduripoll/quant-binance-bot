"""
Configuración central del bot.
Carga variables de entorno y define constantes globales.
"""

import os
from enum import Enum
from dotenv import load_dotenv

load_dotenv()


class BotMode(Enum):
    TEST = "TEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


# ── Modo de operación ──────────────────────────────────────
BOT_MODE = BotMode(os.getenv("BOT_MODE", "TEST"))

# ── Binance ────────────────────────────────────────────────
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

BINANCE_WS_BASE = (
    "wss://testnet.binancefuture.com/ws"
    if BINANCE_TESTNET
    else "wss://fstream.binance.com/ws"
)
BINANCE_REST_BASE = (
    "https://testnet.binancefuture.com"
    if BINANCE_TESTNET
    else "https://fapi.binance.com"
)

# ── Supabase ───────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Risk Management ──────────────────────────────────────
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "0.01"))       # 1% del capital
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "0.05"))               # 5% máx diario
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "10"))
MAX_LEVERAGE = 20

# ── Balance Inicial para TEST/PAPER ──────────────────────
# Capital virtual con el que arranca la simulación
# 50 USDT = equivalente a ~50.000 ARS
TEST_INITIAL_BALANCE = float(os.getenv("TEST_INITIAL_BALANCE", "50"))

# ── Comisiones Binance Futuros ───────────────────────────
MAKER_FEE = 0.0002    # 0.02%
TAKER_FEE = 0.0004    # 0.04%

# ── Timing ────────────────────────────────────────────────
CANDLE_INTERVAL = "5m"
CANDLE_SECONDS = 300
CANDLE_PRE_CLOSE_SECONDS = int(os.getenv("CANDLE_PRE_CLOSE_SECONDS", "3"))

# ── ML ────────────────────────────────────────────────────
ML_MIN_SAMPLES = int(os.getenv("ML_MIN_SAMPLES", "2000"))
ML_RETRAIN_INTERVAL_HOURS = int(os.getenv("ML_RETRAIN_INTERVAL_HOURS", "24"))
ML_MODEL_PATH = "models/scalping_model.joblib"

# ── Trailing Stop ─────────────────────────────────────────
TRAILING_ACTIVATION_RATIO = 0.7       # Activa trailing al 70% del TP
TRAILING_STEP_RATIO = 0.3             # Mueve SL al 30% de la ganancia actual
TRAILING_TP_EXTENSION_RATIO = 0.5     # Extiende TP un 50% adicional
MIN_PROFIT_AFTER_FEES_RATIO = 1.5     # Mínimo 1.5x las comisiones de ganancia

# ── Logging ───────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "logs/scalping_bot.log"
