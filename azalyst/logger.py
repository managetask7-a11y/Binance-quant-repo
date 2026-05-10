from datetime import datetime, timezone
from pathlib import Path


class Logger:
    def __init__(self):
        pass

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)

    def info(self, msg: str):
        self.log(msg, "INFO")

    def debug(self, msg: str):
        self.log(msg, "DEBUG")

    def warn(self, msg: str):
        self.log(msg, "WARN")

    def warning(self, msg: str):
        self.warn(msg)

    def error(self, msg: str):
        self.log(msg, "ERROR")

    def trade(self, msg: str):
        self.log(msg, "TRADE")


logger = Logger()
