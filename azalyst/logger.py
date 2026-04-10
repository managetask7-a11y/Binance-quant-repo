from datetime import datetime, timezone
from pathlib import Path

from azalyst.config import LIVE_LOG_FILE


class Logger:
    def __init__(self, log_file: Path = LIVE_LOG_FILE):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] [{level}] {msg}"
        print(line)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def info(self, msg: str):
        self.log(msg, "INFO")

    def warn(self, msg: str):
        self.log(msg, "WARN")

    def error(self, msg: str):
        self.log(msg, "ERROR")

    def trade(self, msg: str):
        self.log(msg, "TRADE")


logger = Logger()
