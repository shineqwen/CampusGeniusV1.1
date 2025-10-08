import logging
import asyncio
import threading
import time
from telegram.ext import ApplicationBuilder

from config import load_config
from dcu_timetable_service import clear_expired_cache
from handlers import register_handlers
from reminders import ReminderService
import reminders

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("alfred.main")

def periodic_cache_cleanup():
    """Periodic task to clean up expired cache entries (runs in separate thread)"""
    def cleanup_loop():
        while True:
            try:
                time.sleep(300)  # 5 minutes
                clear_expired_cache()
                logger.debug("Cleaned expired cache entries")
            except Exception as e:
                logger.error("Cache cleanup failed: %s", e)
    
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    logger.info("Started background cache cleanup thread")

async def setup_reminder_service(app):
    """Setup and start reminder service"""
    # Initialize reminder service (no longer needs Google Calendar service)
    reminder_service_instance = ReminderService(app.bot)
    
    # Store in global module for access
    reminders.reminder_service = reminder_service_instance
    
    # Start the reminder service
    await reminder_service_instance.start_reminder_service()
    
    logger.info("Reminder service initialized and started")

def main():
    cfg = load_config()

    app = ApplicationBuilder().token(cfg.telegram_token).build()
    app.bot_data["cfg"] = cfg

    register_handlers(app)

    # Start cache cleanup thread
    periodic_cache_cleanup()

    # Setup reminder service after bot initialization
    async def post_init(application):
        await setup_reminder_service(application)
    
    # Add post init handler
    app.post_init = post_init

    logger.info("Alfred bot is online with DCU Timetable integration. Timezone: %s", cfg.timezone.key)
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()