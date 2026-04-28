import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

INITIAL_BALANCE = 100.0
LEVERAGE = 15
RISK_PER_TRADE = 0.14          # 10% risk for bigger winners
ATR_MULT = 4.0           # Max room for 45% Win Rate
TP_RR_RATIO = 2.5              # Higher R:R = bigger runners
SL_MIN_PCT = 0.015
SL_MAX_PCT = 0.04
MAX_OPEN_TRADES = 10
MAX_HOLD_SCANS = 48
BREAKEVEN_AFTER_SCANS = 16     # Restore for stability
SCAN_INTERVAL_MIN = 5        # Alpha-X 15m Scan (Binance Support)
CANDLE_TF_MIN = 15              # Alpha-X 15m Candle (Binance Support)

PROP_MAX_DRAWDOWN_PCT = 50.0
PROP_DAILY_LOSS_PCT = 25.0

TAKER_FEE = 0.0004
SLIPPAGE_BPS = 1.0

MIN_AGREEMENT = 2               # Base agreement (Adaptive engine will upgrade to 3 in chop)
WEIGHTED_THRESHOLD = 5.5       # High precision trigger

BUY = 1
SELL = -1
HOLD = 0

MULTI_WEIGHTS = {
    "bnf": 0.5,
    "nbb": 0.0,            # KILLED: Loser
    "kane": 0.0,           # KILLED: Loser
    "umar": 2.5,             
    "zamco": 0.5,
    "jadecap": 0.2,
    "marci": 0.0,          # KILLED: Loser in long-term
    "fvg": 3.0,              # MASTER STRATEGY
    "ote": 0.0,            # KILLED: Loser
    "cvd_divergence": 0.5,
    "wyckoff": 2.5,
    "cbg": 0.0,            # KILLED: Loser
    "bb_trend": 2.5,         
    "band_rider": 2.5,       
    "liquidity_hunter": 1.0, 
    "alpha_x": 0.0,        # KILLED: Loser
}

HTF_TIMEFRAME = "4h"
HTF_CANDLE_LIMIT = 200
HTF_EMA_FAST = 50
HTF_EMA_SLOW = 200

MAX_SAME_DIRECTION = 5

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

EXCLUDE_SYMBOLS = {
    "USDCUSDT", "TUSDUSDT", "USDPUSDT", "EURUSDT", "FDUSDUSDT",
    "DAIUSDT", "BUSDUSDT", "PAXGUSDT", "USDDUSDT",
}
MIN_VOLUME_MA = 70000
TOP_N_COINS = 20

ORDER_CAP_TIERS = [
    (30,   5),
    (500, 10),
]

TRAILING_STOP_ENABLED = False
