import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_FILE = DATA_DIR / "trader.db"

INITIAL_BALANCE = 100.0
LEVERAGE = 10
RISK_PER_TRADE = 0.10
ATR_MULT = 1.2
TP_RR_RATIO = 1.5
SL_MIN_PCT = 0.01
SL_MAX_PCT = 0.05
MAX_OPEN_TRADES = 10
MAX_HOLD_SCANS = 24
BREAKEVEN_AFTER_SCANS = 4
SCAN_INTERVAL_MIN = 30
CANDLE_TF_MIN = 15

PROP_MAX_DRAWDOWN_PCT = 50.0
PROP_DAILY_LOSS_PCT = 25.0

TAKER_FEE = 0.0004
SLIPPAGE_BPS = 1.0

MIN_AGREEMENT = 2
WEIGHTED_THRESHOLD = 2.5

BUY = 1
SELL = -1
HOLD = 0

MULTI_WEIGHTS = {
    "bnf": 2.0,
    "nbb": 2.0,
    "kane": 1.0,
    "umar": 1.2,
    "zamco": 1.0,
    "jadecap": 0.8,
    "marci": 1.0,
    "fvg": 2.0,
    "ote": 1.5,
    "cvd_divergence": 1.5,
    "wyckoff": 2.0,
}

# Higher-Timeframe Trend Filter
HTF_TIMEFRAME = "4h"
HTF_CANDLE_LIMIT = 200
HTF_EMA_FAST = 50
HTF_EMA_SLOW = 200

# Correlation guard: max trades in same direction
MAX_SAME_DIRECTION = 5

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1479100617283866785/W_vMrnVx40Bb0JLr75AVONGF-Z783MYm-H4IRB17CO9ujA3raNGie5m07vqdgMmwndlG")

EXCLUDE_SYMBOLS = {
    "USDCUSDT", "TUSDUSDT", "USDPUSDT", "EURUSDT", "FDUSDUSDT",
    "DAIUSDT", "BUSDUSDT", "PAXGUSDT", "USDDUSDT",
}
MIN_VOLUME_MA = 75_000
TOP_N_COINS = 100

TELEGRAM_BOT_TOKEN = "7440135340:AAEfgKDeqnXdrRsVVligk1kjf1qTVgKjkYM"
TELEGRAM_CHAT_ID = "1436279105"
