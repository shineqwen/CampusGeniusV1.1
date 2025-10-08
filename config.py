import os
import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("alfred.config")

@dataclass
class BotConfig:
    telegram_token: str
    timezone: ZoneInfo

def load_config() -> BotConfig:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    tz_str = os.getenv("TIMEZONE", "UTC")

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    # Validate and create timezone
    try:
        tz = ZoneInfo(tz_str)
        logger.info(f"Using timezone: {tz_str}")
    except Exception as e:
        logger.warning(f"Invalid timezone '{tz_str}' in config, falling back to UTC: {e}")
        tz = ZoneInfo("UTC")

    return BotConfig(
        telegram_token=token,
        timezone=tz,
    )