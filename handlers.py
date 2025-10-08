import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from agenda import format_agenda
from dcu_timetable_service import fetch_events_for_date_async, get_available_courses, is_valid_course, get_course_info
from user_settings import settings_manager
from quips import random_quip, GREETINGS, DAILY_WISDOM, SETTINGS_QUOTES, CONFIRMATIONS, EVENT_CONFIRMATIONS, ERRORS, UNSUPPORTED_RESPONSES

logger = logging.getLogger("alfred.handlers")

# CACHED KEYBOARDS
@lru_cache(maxsize=50)
def _get_day_keyboard(ref_date_iso: str):
    ref_date = datetime.fromisoformat(ref_date_iso)
    prev_date = (ref_date - timedelta(days=1)).date().isoformat()
    next_date = (ref_date + timedelta(days=1)).date().isoformat()
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀ Prev Day", callback_data=f"nav:{prev_date}"),
            InlineKeyboardButton("Next Day ▶", callback_data=f"nav:{next_date}"),
        ]
    ])

@lru_cache(maxsize=1)
def _get_main_keyboard():
    return ReplyKeyboardMarkup([["Today", "Tomorrow"], ["Settings"]], resize_keyboard=True)

@lru_cache(maxsize=1)
def _get_settings_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Notifications", callback_data="settings:notifications")],
        [InlineKeyboardButton("🕐 Timezone", callback_data="settings:timezone")],
        [InlineKeyboardButton("📚 Course", callback_data="settings:course")],
        [InlineKeyboardButton("💬 Support", callback_data="settings:support")]
    ])

# UTILITY FUNCTIONS
async def _get_user_timezone(user_id: int) -> ZoneInfo:
    """Get user's timezone from settings"""
    user_settings = settings_manager.get_user_settings(user_id)
    if user_settings.timezone != "UTC":
        try:
            return ZoneInfo(user_settings.timezone)
        except Exception:
            logger.warning(f"Invalid timezone {user_settings.timezone} for user {user_id}, using UTC")
    return ZoneInfo("UTC")

async def _prefetch_adjacent_days(course_code: str, day: datetime, tz: ZoneInfo):
    """Prefetch adjacent days for better UX"""
    try:
        prev_day, next_day = day - timedelta(days=1), day + timedelta(days=1)
        await asyncio.gather(
            fetch_events_for_date_async(course_code, prev_day, tz),
            fetch_events_for_date_async(course_code, next_day, tz),
            return_exceptions=True
        )
        logger.debug("Prefetched events for adjacent days")
    except Exception as e:
        logger.warning("Prefetch failed: %s", e)

# CORE HANDLERS
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_first = update.effective_user.first_name or "there"
    user_id = update.effective_user.id
    user_settings = settings_manager.get_user_settings(user_id)
    is_new_user = user_settings.created_at == user_settings.updated_at
    
    course_info = get_course_info(user_settings.course_code)
    course_display = course_info['name'] if course_info else user_settings.course_code
    
    msg = (
        f"{random_quip(GREETINGS, user=user_first)}\n\n"
        f"📚 Current course: <b>{course_display}</b>\n\n"
        "Here is how I am able to help you:\n"
        "• Today – today's timetable\n"
        "• Tomorrow – tomorrow's timetable\n"
        "• Settings – set up notifications, course and more"
    )
    
    if is_new_user:
        msg += "\n\n💡 Pro tip: Go to Settings to configure your course and timezone!"
    
    await update.message.reply_text(msg, reply_markup=_get_main_keyboard(), parse_mode=ParseMode.HTML)

async def _send_day_optimized(update: Update, context: ContextTypes.DEFAULT_TYPE, day: datetime, prefetch: bool = True):
    user_id = update.effective_user.id
    user_settings = settings_manager.get_user_settings(user_id)
    tz = await _get_user_timezone(user_id)
    
    if day.tzinfo != tz:
        day = day.astimezone(tz)
    
    try:
        events = await fetch_events_for_date_async(user_settings.course_code, day, tz)
    except Exception as e:
        logger.error("Failed to fetch events: %s", e)
        events = []
    
    if prefetch:
        asyncio.create_task(_prefetch_adjacent_days(user_settings.course_code, day, tz))
    
    header = f"📅 <b>{day:%A, %d %B}</b>"
    body = format_agenda(events, tz)
    full_text = f"{header}\n\n{body}"
    keyboard = _get_day_keyboard(day.isoformat())
    
    if update.callback_query:
        await update.callback_query.edit_message_text(full_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        await update.callback_query.answer()
    else:
        # Add daily wisdom for fresh requests
        user_name = update.effective_user.first_name or update.effective_user.username or "friend"
        wisdom = random_quip(DAILY_WISDOM, user=user_name, daily=True)
        if wisdom:
            await update.message.reply_text(wisdom)
        await update.message.reply_text(full_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = await _get_user_timezone(update.effective_user.id)
    await _send_day_optimized(update, context, datetime.now(tz))

async def cmd_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = await _get_user_timezone(update.effective_user.id)
    await _send_day_optimized(update, context, datetime.now(tz) + timedelta(days=1))

# ENHANCED MESSAGE HANDLER - Only deletes user message, keeps bot message with buttons
async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clean message handler - only reply keyboard, no inline buttons"""
    text = update.message.text.lower().strip()
    user_message_id = update.message.message_id
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check for supported commands
    if "today" in text:
        await cmd_today(update, context)
        await delete_previous_bot_message(context, chat_id, user_id)
        return
    elif "tomorrow" in text:
        await cmd_tomorrow(update, context)
        await delete_previous_bot_message(context, chat_id, user_id)
        return
    elif "settings" in text:
        await cmd_settings(update, context)
        await delete_previous_bot_message(context, chat_id, user_id)
        return
    
    logger.info(f"Unsupported message from user {update.effective_user.id}: {text}")
    
    # Handle unsupported text - simple message with reply keyboard only
    unsupported_msg = random_quip(UNSUPPORTED_RESPONSES, user=update.effective_user.first_name or "friend", category_name="unsupported")
    
    # Send bot response with ONLY reply keyboard (no inline buttons)
    bot_response = await update.message.reply_text(
        unsupported_msg,
        parse_mode=ParseMode.HTML,
        reply_markup=_get_main_keyboard()
    )
    
    # Store bot message ID for potential deletion when user uses keyboard
    if not hasattr(context, 'bot_message_cache'):
        context.bot_message_cache = {}
    context.bot_message_cache[user_id] = bot_response.message_id
    
    # Delete user's message after delay
    asyncio.create_task(delete_user_message_only(context, chat_id, user_message_id))

async def delete_previous_bot_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """Delete the bot's previous unsupported message when user uses keyboard"""
    if hasattr(context, 'bot_message_cache') and user_id in context.bot_message_cache:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=context.bot_message_cache[user_id])
            logger.debug(f"Deleted previous bot unsupported message for user {user_id}")
            del context.bot_message_cache[user_id]
        except Exception as e:
            logger.warning(f"Failed to delete previous bot message: {e}")

async def delete_user_message_only(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_message_id: int):
    """Delete only the user's message, keep bot's response with buttons"""
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=user_message_id)
        logger.debug(f"Deleted user's unsupported message")
    except Exception as e:
        logger.warning(f"Failed to delete user message: {e}")

async def nav_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    try:
        _, date_str = query.data.split(":", 1)
        day = datetime.fromisoformat(date_str)
        tz = await _get_user_timezone(update.effective_user.id)
        day = day.replace(tzinfo=tz)
        await _send_day_optimized(update, context, day)
    except Exception as e:
        logger.error("Navigation failed: %s", e)
        await query.answer(random_quip(ERRORS))

# SETTINGS SYSTEM
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "⚙️ <b>Settings</b>\n\n"
        f"{random_quip(SETTINGS_QUOTES)}\n\n"
    )
    
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=_get_settings_keyboard())
    else:
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=_get_settings_keyboard())

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified settings handler"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":", 1)[1] if ":" in query.data else query.data
    
    handlers = {
        "main": lambda: cmd_settings(update, context),
        "notifications": lambda: handle_notifications(query, context),
        "timezone": lambda: handle_timezone(query, context),
        "course": lambda: handle_course(query, context),
        "support": lambda: handle_support(query, context)
    }
    
    handler = handlers.get(data)
    if handler:
        await handler()

# COURSE SETTINGS
async def handle_course(query, context):
    """Show faculty selection first"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Faculty of Engineering", callback_data="faculty:engineering")],
        [InlineKeyboardButton("💼 Business School", callback_data="faculty:business")],
        [InlineKeyboardButton("◀ Back", callback_data="settings:main")]
    ])
    
    user_id = query.from_user.id
    user_settings = settings_manager.get_user_settings(user_id)
    course_info = get_course_info(user_settings.course_code)
    current_course_name = course_info['name'] if course_info else user_settings.course_code
    
    msg = (
        "📚 <b>Course Selection</b>\n\n"
        f"Current course: <b>{current_course_name}</b>\n\n"
        "Select your faculty to view available courses:"
    )
    
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def handle_faculty_courses(query, context):
    """Show courses for selected faculty"""
    faculty = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    user_settings = settings_manager.get_user_settings(user_id)
    current_course = user_settings.course_code
    
    available_courses = get_available_courses()
    
    if faculty == "engineering":
        faculty_name = "⚙️ Faculty of Engineering"
        faculty_courses = {k: v for k, v in available_courses.items()
                          if v.get('faculty') == 'engineering'}
    else:
        faculty_name = "💼 Business School"
        faculty_courses = {k: v for k, v in available_courses.items()
                          if v.get('faculty') == 'business'}
    
    if not faculty_courses:
        logger.warning(f"No courses found for faculty {faculty}, showing all courses as fallback")
        faculty_courses = available_courses
    
    buttons = []
    for course_code, course_info in faculty_courses.items():
        is_current = course_code == current_course
        prefix = "✅ " if is_current else ""
        suffix = " (Current)" if is_current else ""
        button_text = f"{prefix}{course_info['name']}{suffix}"
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"course_set:{course_code}")])
    
    buttons.append([InlineKeyboardButton("◀ Back to Faculties", callback_data="settings:course")])
    
    keyboard = InlineKeyboardMarkup(buttons)
    
    msg = (
        f"<b>{faculty_name}</b>\n\n"
        "Select your course:"
    )
    
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def course_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("faculty:"):
        await handle_faculty_courses(query, context)
    elif data.startswith("course_set:"):
        course_code = data.split(":", 1)[1]
        user_id = update.effective_user.id
        
        if is_valid_course(course_code):
            settings_manager.update_user_setting(user_id, course_code=course_code)
            course_info = get_course_info(course_code)
            course_name = course_info['name'] if course_info else course_code
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 View Today's Schedule", callback_data="quick:today")],
                [InlineKeyboardButton("📚 Back to Course Selection", callback_data="settings:course")],
                [InlineKeyboardButton("🏠 Main Settings", callback_data="settings:main")]
            ])
            
            msg = (
                f"✅ <b>Course Updated!</b>\n\n"
                f"Your course is now set to:\n<b>{course_name}</b>\n\n"
                "All timetable data will now be fetched for this course.\n\n"
                "What would you like to do next?"
            )
            
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        else:
            await query.edit_message_text("❌ Invalid course selected. Please try again.", parse_mode=ParseMode.HTML)

# NOTIFICATIONS SYSTEM
async def handle_notifications(query, context):
    user_id = query.from_user.id
    user_settings = settings_manager.get_user_settings(user_id)
    
    daily_status = "✅ Enabled" if user_settings.daily_reminders else "❌ Disabled"
    event_status = "✅ Enabled" if user_settings.event_reminders else "❌ Disabled"
    
    buttons = [
        [
            InlineKeyboardButton("🔄 Daily", callback_data="notif_enable:daily" if not user_settings.daily_reminders else "notif_disable:daily"),
            InlineKeyboardButton("🕐 Events", callback_data="notif_enable:event" if not user_settings.event_reminders else "notif_disable:event")
        ],
        [InlineKeyboardButton("⚙️ Configure Times", callback_data="config:times")],
        [InlineKeyboardButton("◀ Back", callback_data="settings:main")]
    ]
    
    keyboard = InlineKeyboardMarkup(buttons)
    
    msg = (
        "🔔 <b>Notification Settings</b>\n\n"
        f"Daily reminders: {daily_status}\n"
        f"Times: <b>{user_settings.morning_time}</b> & <b>{user_settings.evening_time}</b>\n\n"
        f"Event reminders: {event_status}\n"
        f"Event timing: <b>{user_settings.event_reminder_minutes} Minutes</b>\n\n"
        "Use buttons to enable/disable or configure times:"
    )
    
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def notification_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    action, setting = query.data.split(":", 1)
    
    if action in ["notif_enable", "notif_disable"]:
        enable = action == "notif_enable"
        if setting == "daily":
            settings_manager.update_user_setting(user_id, daily_reminders=enable)
            status = "enabled" if enable else "disabled"
            await query.answer(f"Daily reminders {status}!", show_alert=True)
        elif setting == "event":
            settings_manager.update_user_setting(user_id, event_reminders=enable)
            status = "enabled" if enable else "disabled"
            await query.answer(f"Event reminders {status}!", show_alert=True)
        
        await handle_notifications(query, context)
    
    elif action == "config":
        if setting == "times":
            buttons = [
                [InlineKeyboardButton("🌆 Morning Buzz", callback_data="time_config:morning")],
                [InlineKeyboardButton("🌙 Evening Buzz", callback_data="time_config:evening")],
                [InlineKeyboardButton("🕐 Before Event", callback_data="time_config:event")],
                [InlineKeyboardButton("◀ Back", callback_data="settings:notifications")]
            ]
            
            keyboard = InlineKeyboardMarkup(buttons)
            user_settings = settings_manager.get_user_settings(user_id)
            
            msg = (
                "⚙️ <b>Time Configuration</b>\n\n"
                "Current settings:\n\n"
                f"Morning Buzz: <b>{user_settings.morning_time}</b>\n"
                f"Evening Buzz: <b>{user_settings.evening_time}</b>\n\n"
                f"Event Alerts: <b>{user_settings.event_reminder_minutes} Minutes</b>\n\n"
                "⬇️ Tap to modify"
            )
            
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def time_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith("time_config:"):
        config_type = data.split(":", 1)[1]
        user_settings = settings_manager.get_user_settings(user_id)
        
        if config_type == "morning":
            time_options = [
                ("06:00", "6:00 AM"), ("07:00", "7:00 AM"), ("08:00", "8:00 AM"),
                ("09:00", "9:00 AM"), ("10:00", "10:00 AM")
            ]
            
            buttons = []
            for time_val, time_display in time_options:
                prefix = "✅ " if time_val == user_settings.morning_time else ""
                buttons.append([InlineKeyboardButton(f"{prefix}{time_display}", callback_data=f"set_morning:{time_val}")])
            
            buttons.append([InlineKeyboardButton("◀ Back", callback_data="config:times")])
            keyboard = InlineKeyboardMarkup(buttons)
            
            msg = (
                "🌆 <b>Morning Reminder Time</b>\n\n"
                f"Current: <b>{user_settings.morning_time}</b>\n\n"
                "When should I send your morning agenda?"
            )
        
        elif config_type == "evening":
            time_options = [
                ("17:00", "5:00 PM"), ("18:00", "6:00 PM"), ("19:00", "7:00 PM"),
                ("20:00", "8:00 PM"), ("21:00", "9:00 PM"), ("22:00", "10:00 PM")
            ]
            
            buttons = []
            for time_val, time_display in time_options:
                prefix = "✅ " if time_val == user_settings.evening_time else ""
                buttons.append([InlineKeyboardButton(f"{prefix}{time_display}", callback_data=f"set_evening:{time_val}")])
            
            buttons.append([InlineKeyboardButton("◀ Back", callback_data="config:times")])
            keyboard = InlineKeyboardMarkup(buttons)
            
            msg = (
                "🌙 <b>Evening Reminder Time</b>\n\n"
                f"Current: <b>{user_settings.evening_time}</b>\n\n"
                "When should I send tomorrow's agenda?"
            )
        
        elif config_type == "event":
            # Event timing selection - added 45 minutes option
            timing_options = [
                (5, "5 minutes"), (10, "10 minutes"), (15, "15 minutes"),
                (20, "20 minutes"), (30, "30 minutes"), (45, "45 minutes"), (60, "1 hour")
            ]
                    
            buttons = []
            for minutes, display in timing_options:
                prefix = "✅ " if minutes == user_settings.event_reminder_minutes else ""
                buttons.append([InlineKeyboardButton(f"{prefix}{display}", callback_data=f"set_event:{minutes}")])
            
            buttons.append([InlineKeyboardButton("◀ Back", callback_data="config:times")])
            keyboard = InlineKeyboardMarkup(buttons)
            
            msg = (
                "🕐 <b>Reminder Before Event</b>\n\n"
                f"Current: <b>{user_settings.event_reminder_minutes} Minutes</b> Before\n\n"
                "How early should I remind you about upcoming events?"
            )
        
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    
    elif data.startswith("set_morning:"):
        time_val = data.split(":", 1)[1]
        settings_manager.update_user_setting(user_id, morning_time=time_val)
        await query.answer(f"Morning time set to {time_val}!", show_alert=True)
        await time_config_handler_show_menu(query, context, user_id)
    
    elif data.startswith("set_evening:"):
        time_val = data.split(":", 1)[1]
        settings_manager.update_user_setting(user_id, evening_time=time_val)
        await query.answer(f"Evening time set to {time_val}!", show_alert=True)
        await time_config_handler_show_menu(query, context, user_id)
    
    elif data.startswith("set_event:"):
        minutes = int(data.split(":", 1)[1])
        settings_manager.update_user_setting(user_id, event_reminder_minutes=minutes)
        await query.answer(f"Event reminder set to {minutes} minutes before!", show_alert=True)
        await time_config_handler_show_menu(query, context, user_id)

async def time_config_handler_show_menu(query, context, user_id):
    """Helper to show the time config menu after setting a value"""
    buttons = [
        [InlineKeyboardButton("🌅 Morning Time", callback_data="time_config:morning")],
        [InlineKeyboardButton("🌙 Evening Time", callback_data="time_config:evening")],
        [InlineKeyboardButton("⏰ Event Timing", callback_data="time_config:event")],
        [InlineKeyboardButton("◀ Back", callback_data="settings:notifications")]
    ]
    
    keyboard = InlineKeyboardMarkup(buttons)
    user_settings = settings_manager.get_user_settings(user_id)
    
    msg = (
        "⚙️ Time Configuration\n\n"
        f"Current settings:\n"
        f"• Morning: {user_settings.morning_time}\n"
        f"• Evening: {user_settings.evening_time}\n"
        f"• Event timing: {user_settings.event_reminder_minutes}min before\n\n"
        "What would you like to configure?"
    )
    
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

# TIMEZONE SYSTEM
async def handle_timezone(query, context, page=0):
    user_id = query.from_user.id
    user_settings = settings_manager.get_user_settings(user_id)
    current_tz = user_settings.timezone
    
    page_timezones, total_pages, has_prev, has_next = settings_manager.get_timezone_page(page)
    
    buttons = []
    for tz_info in page_timezones:
        tz_name, tz_id = tz_info["name"], tz_info["tz"]
        is_current = tz_id == current_tz
        prefix = "✅ " if is_current else ""
        button_text = f"{prefix}{tz_name}"
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"tz_set:{tz_id}")])
    
    nav_buttons = []
    if has_prev:
        nav_buttons.append(InlineKeyboardButton("◀", callback_data=f"tz_page:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="tz_info"))
    if has_next:
        nav_buttons.append(InlineKeyboardButton("▶", callback_data=f"tz_page:{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("◀ Back", callback_data="settings:main")])
    
    keyboard = InlineKeyboardMarkup(buttons)
    
    msg = (
        "🕐 <b>Timezone Configuration</b>\n\n"
        f"Current: <b>{current_tz}</b>\n\n"
        "Select your timezone:"
    )
    
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def timezone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith("tz_set:"):
        timezone_str = data.split(":", 1)[1]
        if settings_manager.is_valid_timezone(timezone_str):
            settings_manager.update_user_setting(user_id, timezone=timezone_str)
            msg = f"✅ Timezone Updated!\n\nYour timezone is now: {timezone_str}"
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text("❌ Invalid timezone. Please try again.", parse_mode=ParseMode.HTML)
    
    elif data.startswith("tz_page:"):
        page = int(data.split(":", 1)[1])
        await handle_timezone(query, context, page)
    
    elif data == "tz_info":
        await query.answer("Use ◀ ▶ to navigate", show_alert=True)

# SUPPORT
async def handle_support(query, context):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("◀ Back", callback_data="settings:main")]])
    msg = (
        "💬 <b>Support & Contact</b>\n\n"
        "Need help? Or just want to complain about lectures?\n"
        "Ping my developer: @shineqwen 🛠️"
    )
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)

# QUICK ACTIONS
async def quick_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quick action buttons after course selection"""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split(":", 1)[1]
    
    if action == "today":
        user_id = update.effective_user.id
        tz = await _get_user_timezone(user_id)
        today = datetime.now(tz)
        await _send_day_optimized(update, context, today, prefetch=False)

# REMINDER ACTIONS
async def reminder_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reminder button actions like 'View Today'"""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split(":", 1)[1]
    
    if action == "view_today":
        # Show today's full schedule
        user_id = update.effective_user.id
        user_settings = settings_manager.get_user_settings(user_id)
        tz = await _get_user_timezone(user_id)
        today = datetime.now(tz)
        
        # Fetch events
        try:
            events = await fetch_events_for_date_async(user_settings.course_code, today, tz)
        except Exception as e:
            logger.error("Failed to fetch events: %s", e)
            events = []
        
        # Format agenda
        header = f"📅 <b>{today:%A, %d %B}</b>"
        body = format_agenda(events, tz)
        full_text = f"{header}\n\n{body}"
        
        # Create navigation keyboard
        keyboard = _get_day_keyboard(today.isoformat())
        
        # Edit the reminder message to show the agenda
        await query.edit_message_text(full_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

# REGISTRATION
def register_handlers(app):
    # Core commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    
    # Navigation
    app.add_handler(CallbackQueryHandler(nav_handler, pattern=r"^nav:"))
    
    # Settings system
    app.add_handler(CallbackQueryHandler(settings_handler, pattern=r"^settings:"))
    app.add_handler(CallbackQueryHandler(course_handler, pattern=r"^(faculty|course_set):"))
    app.add_handler(CallbackQueryHandler(notification_handler, pattern=r"^(notif_enable|notif_disable|config):"))
    app.add_handler(CallbackQueryHandler(time_config_handler, pattern=r"^(time_config|set_morning|set_evening|set_event):"))
    app.add_handler(CallbackQueryHandler(timezone_handler, pattern=r"^(tz_set|tz_page|tz_info)"))
    
    # Quick actions
    app.add_handler(CallbackQueryHandler(quick_action_handler, pattern=r"^quick:"))
    
    # Reminder actions
    app.add_handler(CallbackQueryHandler(reminder_action_handler, pattern=r"^reminder:"))


def clear_handler_cache():
    _get_day_keyboard.cache_clear()
    _get_main_keyboard.cache_clear()
    _get_settings_keyboard.cache_clear()