from datetime import datetime, timezone

from azalyst.config import DISCORD_WEBHOOK_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from azalyst.logger import logger

def send_discord_alert(title: str, message: str):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        import requests
        payload = {
            "embeds": [{
                "title": title,
                "description": message,
                "color": 5763719,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        logger.warn(f"Failed to send Discord alert: {e}")

def send_telegram_alert(title: str, message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        text = f"*{title}*\n\n{message}"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        logger.warn(f"Failed to send Telegram alert: {e}")

def send_alerts(title: str, message: str):
    send_discord_alert(title, message)
    send_telegram_alert(title, message)
