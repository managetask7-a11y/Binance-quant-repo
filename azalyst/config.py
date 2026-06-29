import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

INITIAL_BALANCE = 100
LEVERAGE = 15
MARGIN_PER_TRADE_PCT = 0.12  # 12% of balance as margin (~$7 on a $58 account). Set to 0 to use strict Risk-Based sizing.
RISK_PER_TRADE = 0.07
ATR_MULT = 1.4
TP_RR_RATIO = 2.0
SL_MIN_PCT = 0.01
SL_MAX_PCT = 0.03
MAX_OPEN_TRADES = 10
MAX_HOLD_SCANS = 48
BREAKEVEN_AFTER_SCANS = 10
SCAN_INTERVAL_MIN = 15  # Scan once per candle close (must match CANDLE_TF_MIN for backtest parity)
CANDLE_TF_MIN = 15

PROP_MAX_DRAWDOWN_PCT = 50.0
PROP_DAILY_LOSS_PCT = 25.0

TAKER_FEE = 0.0004
SLIPPAGE_BPS = 1.0

MIN_AGREEMENT = 1
WEIGHTED_THRESHOLD = 5.0

BUY = 1
SELL = -1
HOLD = 0

MULTI_WEIGHTS = {
    "bnf": 5.0,
    "nbb": 1.5,
    "kane": 0.8,
    "umar": 1.8,
    "zamco": 0.5,
    "jadecap": 0.5,
    "marci": 1.5,
    "fvg": 1.5,
    "ote": 1.0,
    "cvd_divergence": 0.5,
    "wyckoff": 1.5,
    "cbg": 1.2,
    "bb_trend": 1.8,
    "band_rider": 0.0,
    "liquidity_hunter": 3.0,
    "alpha_x": 0.0,
    "quantx": 2.0,
    "ema5": 1.5,
    "smt_divergence": 1.8,
    "jadecap_sweep": 2.0,
}

HTF_TIMEFRAME = "4h"
HTF_CANDLE_LIMIT = 1000
HTF_EMA_FAST = 50
HTF_EMA_SLOW = 200

MAX_SAME_DIRECTION = 5

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

EXCLUDE_SYMBOLS = {
    "USDCUSDT", "TUSDUSDT", "USDPUSDT", "EURUSDT", "FDUSDUSDT",
    "DAIUSDT", "BUSDUSDT", "PAXGUSDT", "USDDUSDT",
    "DOGEUSDT",
    "VIRTUAL/USDT:USDT", "ORCA/USDT:USDT", "AR/USDT:USDT", "M/USDT:USDT", "SWARMS/USDT:USDT",
    "ZEC/USDT:USDT", "BNB/USDT:USDT", "RE/USDT:USDT", "MANTA/USDT:USDT",
    "XRP/USDT:USDT", "VELVET/USDT:USDT", "LAB/USDT:USDT", "NEAR/USDT:USDT",
    "币安人生/USDT:USDT", "AAVE/USDT:USDT",
}

GOLD_COINS = [
    "TAO/USDT:USDT", "LINK/USDT:USDT", "SKYAI/USDT:USDT", "TRX/USDT:USDT",
    "BEAT/USDT:USDT",
]

LONG_ONLY_COINS = [
    "MSTR/USDT:USDT", "KAITO/USDT:USDT", "XAU/USDT:USDT", "JTO/USDT:USDT",
    "HYPE/USDT:USDT", "ZEREBRO/USDT:USDT", "AGLD/USDT:USDT", "ALLO/USDT:USDT",
    "MAGMA/USDT:USDT",
]

SHORT_ONLY_COINS = [
    "XLM/USDT:USDT", "UNI/USDT:USDT", "CL/USDT:USDT", "TRUMP/USDT:USDT",
    "GUA/USDT:USDT", "SNX/USDT:USDT", "SLX/USDT:USDT", "ACT/USDT:USDT",
    "ID/USDT:USDT", "PIEVERSE/USDT:USDT", "SOL/USDT:USDT", "EIGEN/USDT:USDT",
]

MIN_VOLUME_MA = 70000
TOP_N_COINS = 20

ORDER_CAP_TIERS = [
    (30,   5),
    (500, 10),
]

TRAILING_STOP_ENABLED = False

REGIME_SMOOTHING_PERIOD = 5
REGIME_BTC_SYMBOL = "BTC/USDT:USDT"

SCAN_LIMITS = {
    "strong_uptrend": 20,
    "weak_uptrend": 20,
    "sideways": 15,
    "weak_downtrend": 10,
    "strong_downtrend": 10,
}
