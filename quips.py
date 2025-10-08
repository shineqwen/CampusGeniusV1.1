import random
from datetime import date, datetime

# --- Memory for avoiding repeats & daily/weekly limits ---
_last_used = {}
_last_used_day = {}
_last_used_week = {}

def _choose_non_repeating(category: list, user: str, category_name: str) -> str:
    """Pick a random quip ensuring it's not the same as last time for this user."""
    key = (user, category_name)
    last = _last_used.get(key)

    choices = [q for q in category if q != last] or category
    chosen = random.choice(choices)

    _last_used[key] = chosen
    return chosen.format(user=user)

def random_quip(category: list, user: str = "friend", category_name: str = None, daily: bool = False) -> str | None:
    """
    Return a witty quip, avoiding repetition.
    If daily=True, only return once per user per day; afterwards returns None.
    """
    category_name = category_name or str(id(category))
    today = date.today()
    key = (user, category_name)

    if daily:
        last_day = _last_used_day.get(key)
        if last_day == today:
            return None
        _last_used_day[key] = today

    return _choose_non_repeating(category, user, category_name)

def weekly_quip(user: str = "friend") -> str | None:
    """Return a quip once per week, depending on the weekday."""
    today = date.today()
    week_key = (user, "weekly_quip")

    # Already sent this week
    last_week = _last_used_week.get(week_key)
    if last_week == today.isocalendar()[1]:  # week number
        return None

    _last_used_week[week_key] = today.isocalendar()[1]
    weekday = today.weekday()  # 0 = Monday, 6 = Sunday

    if weekday == 0:  # Monday
        return f"☕ Monday mode: {user}, brace yourself. Productivity is optional."
    elif weekday == 2:  # Wednesday
        return f"🪐 Happy Hump Day, {user}! You're halfway through the chaos."
    elif weekday == 4:  # Friday
        return f"🎉 It's Friday, {user}! Meetings can't hurt you anymore… almost."
    elif weekday in (5, 6):  # Saturday / Sunday
        return f"🍹 Weekend detected. {user}, cancel everything and relax."
    else:
        return f"⚡ Keep going, {user}! You're doing better than your calendar looks."



# --- GREETINGS ---
GREETINGS = [
    "Ah, you've summoned me again, human. Genius reporting for duty 🕴️",
    "Behold! The mighty agenda-bot awakens ⚡",
    "At your service, Master Wayne... err, I mean, {user} 🦇",
    "Greetings, {user}. I come bearing calendars and questionable humor 📅",
    "Hello {user}! Prepare yourself for meetings, deadlines, and mild existential dread ☕"
]

# --- DAILY QUOTES (Agenda Fetching) ---
DAILY_QUOTES = [
    "Try not to cancel everything like last Tuesday 😅",
    "Productivity level: loading… please don't snooze your meetings again ⏰",
    "Here's your agenda. May the odds of finishing it be ever in your favor 🎯",
    "Meetings ahead. Brace yourself… ☕",
    "This list looks intense. I recommend snacks and emotional support 🥨"
]

# --- DAILY WISDOM (One per user per day) ---
DAILY_WISDOM = [
    "🧠 Wisdom of the day: If you don't schedule it, it doesn't exist.",
    "💡 Pro tip: Meetings are just emails that wanted to feel important.",
    "🎭 Remember: life is just a series of calendar invites.",
    "🍕 Motivation: Finish your agenda and reward yourself with pizza.",
    "☕ Fun fact: 73% of productivity is powered by coffee. The rest is lies."
]

# --- SETTINGS MENU ---
SETTINGS_QUOTES = [
    "Time to tinker with my circuits! What shall we tweak today? ⚙️🤖",
    "Settings: where dreams of productivity go to die 🔧",
    "Choose wisely… these settings could alter the space-time continuum 🌀",
    "Welcome to the control room, {user}. Please don't break anything 🚨",
    "Settings unlocked. Feels like opening Pandora's box, doesn't it? 📦"
]

# --- CONFIRMATIONS (Daily reminders) ---
CONFIRMATIONS = [
    "✅ All set! I will now bug you daily. Don't shoot the messenger 😎",
    "✅ Notifications enabled. Prepare for unsolicited productivity spam 📲",
    "✅ Got it. Expect me at 7AM sharp. No snooze button included ⏰",
    "✅ Daily reminders engaged. I'll wake you up like an annoying alarm clock 🛎️"
]

# --- EVENT REMINDER CONFIRMATIONS ---
EVENT_CONFIRMATIONS = [
    "✅ Event reminders armed! I'll be your personal hype-man 20 mins before chaos 🎤",
    "✅ Locked in. You'll hear from me before each meeting. Like it or not 👀",
    "✅ Done. I'll buzz you before events, because Google Calendar isn't clingy enough 📅",
    "✅ Enabled. Think of me as your bossy sidekick ⏰"
]

# --- ERRORS ---
ERRORS = [
    "😅 Whoops, my circuits tripped. Navigation failed. Try again?",
    "🤖 Error: Genius.exe has stopped working. Just kidding, click again.",
    "⚠️ Plot twist: I don't know what went wrong. Let's blame Mercury retrograde.",
    "💥 System hiccup. Probably your fault, {user}. Kidding (or am I?)"
]

# --- UNSUPPORTED MESSAGE RESPONSES ---
UNSUPPORTED_RESPONSES = [
    "🤖 Hmm, I didn't quite catch that. Try using the buttons below! 👇",
    "⚠️ That's not in my vocabulary yet. Stick to the menu options! 📋",
    "🧐 Although I'm Genius, but still not a mind reader. Use the buttons or commands! 🎯",
    "🔧 This isn't a supported command. Check out what I can do! 🛠️",
    "📱 I speak emoji and buttons, not hieroglyphics! Try the menu! 🗂️",
    "🎭 That's Greek to me! Use the available options instead! 🎪",
    "🎯 Close, but no cigar! Stick to the provided commands! 🚀",
    "🔍 Command not found in my database! Use the buttons! 💾"
]

# --- REMINDERS (Morning / Evening) ---
REMINDER_MORNING = [
    "🌅 Good morning! Coffee in one hand, agenda in the other ☕📅",
    "Rise and shine, {user}! Time to pretend you love meetings ✨",
    "Morning, {user}! Don't worry, I already judged your sleep schedule 😴",
    "🌞 Wake up, {user}! Your calendar is waiting with open arms (and deadlines) 📌"
]

REMINDER_EVENING = [
    "🌙 Evening check-in: here's tomorrow's chaos, neatly wrapped 🎁",
    "Planning ahead? Look at you being all responsible 👏",
    "Don't stay up binge-watching… again 👀 Tomorrow's waiting for you.",
    "🌜 Bedtime story: tomorrow's agenda. Spoiler, it's less fun than Netflix 📺"
]