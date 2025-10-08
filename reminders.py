import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from user_settings import settings_manager
from dcu_timetable_service import fetch_events_for_date
from agenda import format_agenda
from quips import random_quip, REMINDER_MORNING, REMINDER_EVENING, DAILY_WISDOM, weekly_quip

logger = logging.getLogger("alfred.reminders")

class ReminderService:
    def __init__(self, bot):
        self.bot = bot
        self.running = False
        self.sent_event_reminders = set()  # Track sent reminders to avoid duplicates
        self.user_message_history = {}  # Track message IDs for cleanup: {user_id: [msg_ids]}
    
    async def start_reminder_service(self):
        if self.running:
            return
        self.running = True
        logger.info("Starting reminder service with extra sass 😎")
        asyncio.create_task(self._daily_reminder_loop())
        asyncio.create_task(self._event_reminder_loop())
    
    async def stop_reminder_service(self):
        self.running = False
        logger.info("Stopping reminder service… don't miss me too much 💔")
    
    async def _get_user_timezone(self, user_id: int) -> ZoneInfo:
        """Get user's timezone from settings"""
        user_settings = settings_manager.get_user_settings(user_id)
        
        # If user has manually set timezone in settings, use that
        if user_settings.timezone != "UTC":
            try:
                return ZoneInfo(user_settings.timezone)
            except Exception:
                logger.warning(f"Invalid timezone {user_settings.timezone} for user {user_id}, using UTC")
        
        # Default to UTC
        return ZoneInfo("UTC")
    
    async def _get_user_display_name(self, user_id: int) -> str:
        """Get user's display name from Telegram"""
        try:
            chat = await self.bot.get_chat(user_id)
            if chat.first_name:
                return chat.first_name
            elif chat.username:
                return chat.username
            else:
                return f"User{user_id}"
        except Exception as e:
            logger.warning(f"Could not get display name for user {user_id}: {e}")
            return f"User{user_id}"
    
    async def _cleanup_old_messages(self, user_id: int):
        """Delete all previous bot messages for the user"""
        if user_id not in self.user_message_history:
            return
        
        message_ids = self.user_message_history[user_id]
        deleted_count = 0
        
        for msg_id in message_ids:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=msg_id)
                deleted_count += 1
            except Exception as e:
                logger.debug(f"Could not delete message {msg_id} for user {user_id}: {e}")
        
        # Clear the history after cleanup
        self.user_message_history[user_id] = []
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old messages for user {user_id}")
    
    def _track_message(self, user_id: int, message_id: int):
        """Track a message ID for future cleanup"""
        if user_id not in self.user_message_history:
            self.user_message_history[user_id] = []
        self.user_message_history[user_id].append(message_id)
        
        # Keep only last 100 messages to avoid memory issues
        if len(self.user_message_history[user_id]) > 100:
            self.user_message_history[user_id] = self.user_message_history[user_id][-100:]
    
    async def _daily_reminder_loop(self):
        while self.running:
            try:
                current_time = datetime.now(ZoneInfo("UTC"))
                await self._send_morning_reminders(current_time)
                await self._send_evening_reminders(current_time)
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in daily reminder loop: {e}")
                await asyncio.sleep(60)
    
    async def _event_reminder_loop(self):
        while self.running:
            try:
                await self._send_event_reminders()
                await asyncio.sleep(60)
                
                # Clean old event reminder tracking every hour
                if datetime.now().minute == 0:
                    self._cleanup_sent_reminders()
            except Exception as e:
                logger.error(f"Error in event reminder loop: {e}")
                await asyncio.sleep(60)
    
    def _cleanup_sent_reminders(self):
        """Clean up old sent reminder tracking"""
        current_time = datetime.now()
        # Remove reminders older than 2 hours
        cutoff_time = current_time - timedelta(hours=2)
        self.sent_event_reminders = {
            reminder_key for reminder_key in self.sent_event_reminders
            if not reminder_key.startswith(cutoff_time.strftime("%Y%m%d%H"))
        }
    
    async def _send_morning_reminders(self, current_time: datetime):
        users = settings_manager.get_users_with_daily_reminders()
        for user_settings in users:
            try:
                user_tz = await self._get_user_timezone(user_settings.user_id)
                user_time = current_time.astimezone(user_tz)
                morning_hour, morning_minute = map(int, user_settings.morning_time.split(':'))
                if user_time.hour == morning_hour and user_time.minute == morning_minute:
                    # Clean up old messages before sending morning reminder
                    await self._cleanup_old_messages(user_settings.user_id)
                    await self._send_daily_agenda(user_settings.user_id, user_time, "morning", user_tz, user_settings.course_code)
            except Exception as e:
                logger.error(f"Failed morning reminder for {user_settings.user_id}: {e}")
    
    async def _send_evening_reminders(self, current_time: datetime):
        users = settings_manager.get_users_with_daily_reminders()
        for user_settings in users:
            try:
                user_tz = await self._get_user_timezone(user_settings.user_id)
                user_time = current_time.astimezone(user_tz)
                evening_hour, evening_minute = map(int, user_settings.evening_time.split(':'))
                if user_time.hour == evening_hour and user_time.minute == evening_minute:
                    tomorrow = user_time + timedelta(days=1)
                    await self._send_daily_agenda(user_settings.user_id, tomorrow, "evening", user_tz, user_settings.course_code)
            except Exception as e:
                logger.error(f"Failed evening reminder for {user_settings.user_id}: {e}")
    
    async def _send_daily_agenda(self, user_id: int, day: datetime, reminder_type: str, user_tz: ZoneInfo, course_code: str):
        try:
            # Get user's display name
            user_name = await self._get_user_display_name(user_id)
            
            # === SINGLE MESSAGE: Greeting with "View Today" button ===
            greeting_message = None
            
            # For evening reminders, skip weekly quips and use evening-appropriate greetings
            if reminder_type == "evening":
                # Always use evening greeting for consistency
                greeting = random_quip(
                    REMINDER_EVENING,
                    user=user_name,
                    category_name="evening_greeting"
                )
                greeting_message = greeting
            else:
                # For morning reminders, use weekly quip if available
                wquip = weekly_quip(user=user_name)
                if wquip:
                    greeting_message = wquip
                else:
                    # Only add daily morning greeting if no weekly quip
                    greeting = random_quip(
                        REMINDER_MORNING,
                        user=user_name,
                        category_name="morning_greeting"
                    )
                    greeting_message = greeting
            
            # Create inline keyboard with "View Today" button
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 View Today's Schedule", callback_data="reminder:view_today")]
            ])
            
            # Send greeting message with button
            if greeting_message:
                sent_message = await self.bot.send_message(
                    chat_id=user_id,
                    text=greeting_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard
                )
                
                # Track the message for future cleanup
                self._track_message(user_id, sent_message.message_id)

            logger.info(f"Sent {reminder_type} reminder to user {user_id} ({user_name}) for course {course_code}")

        except TelegramError as e:
            if "chat not found" in str(e).lower() or "blocked" in str(e).lower():
                logger.warning(f"User {user_id} blocked bot, disabling reminders")
                settings_manager.update_user_setting(user_id, daily_reminders=False, event_reminders=False)
            else:
                logger.error(f"Telegram error sending reminder to {user_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to send daily agenda to {user_id}: {e}")
    
    async def _send_event_reminders(self):
        users = settings_manager.get_users_with_event_reminders()
        current_time = datetime.now(ZoneInfo("UTC"))
        
        for user_settings in users:
            try:
                user_tz = await self._get_user_timezone(user_settings.user_id)
                today = current_time.astimezone(user_tz)
                events = await fetch_events_for_date(user_settings.course_code, today, user_tz)
                
                for event in events:
                    await self._check_event_reminder(user_settings, event, current_time, user_tz)
            except Exception as e:
                logger.error(f"Failed to check event reminders for {user_settings.user_id}: {e}")
    
    async def _check_event_reminder(self, user_settings, event: dict, current_time: datetime, user_tz: ZoneInfo):
        try:
            start_info = event.get("start", {})
            if "dateTime" not in start_info:
                return  # Skip all-day events
            
            event_start = datetime.fromisoformat(start_info["dateTime"].replace("Z", "+00:00"))
            event_start_local = event_start.astimezone(user_tz)
            current_local = current_time.astimezone(user_tz)
            
            # Calculate time difference
            time_diff = event_start_local - current_local
            reminder_minutes = user_settings.event_reminder_minutes
            
            # Check if we should send reminder (exactly at the reminder time, ±30 seconds tolerance)
            target_diff = timedelta(minutes=reminder_minutes)
            tolerance = timedelta(seconds=30)
            
            if abs(time_diff - target_diff) <= tolerance:
                # Create unique reminder key to prevent duplicates
                event_id = event.get("id", "unknown")
                reminder_key = f"{user_settings.user_id}_{event_id}_{event_start_local.isoformat()}"
                
                if reminder_key in self.sent_event_reminders:
                    return  # Already sent this reminder
                
                self.sent_event_reminders.add(reminder_key)
                
                # Get user's display name
                user_name = await self._get_user_display_name(user_settings.user_id)
                
                # Build reminder message
                event_title = event.get("summary", "(No title)")
                location = event.get("location", "")
                staff = event.get("staff", "")
                
                # Updated message format: removed "Reminder:" and "Type" row, added gap
                message = f"⏰ <b>{event_title} starts in {reminder_minutes} minutes!</b>\n\n"
                message += f"🕐 <b>{event_start_local:%H:%M}</b>\n"
                
                if location:
                    message += f"📍 {location}\n"
                
                if staff:
                    message += f"👨‍🏫 Staff: {staff}\n"
                
                sent_message = await self.bot.send_message(
                    chat_id=user_settings.user_id, 
                    text=message, 
                    parse_mode=ParseMode.HTML
                )
                
                # Track event reminder messages too
                self._track_message(user_settings.user_id, sent_message.message_id)
                
                logger.info(f"Sent event reminder to user {user_settings.user_id} ({user_name}) for event: {event_title}")
                
        except Exception as e:
            logger.error(f"Failed event reminder for {user_settings.user_id}: {e}")

# Global reminder service instance
reminder_service = None