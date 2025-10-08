import logging
import os
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from zoneinfo import ZoneInfo
from pymongo import MongoClient

logger = logging.getLogger("alfred.user_settings")

# UTC-based timezone choices for settings UI (offset-based)
UTC_TIMEZONES = [
    {"name": "UTC", "offset": 0, "tz": "UTC"},
    {"name": "UTC+1", "offset": 1, "tz": "Europe/London"},
    {"name": "UTC+2", "offset": 2, "tz": "Europe/Berlin"},
    {"name": "UTC+3", "offset": 3, "tz": "Europe/Moscow"},
    {"name": "UTC+4", "offset": 4, "tz": "Asia/Dubai"},
    {"name": "UTC+5", "offset": 5, "tz": "Asia/Karachi"},
    {"name": "UTC+5:30", "offset": 5.5, "tz": "Asia/Kolkata"},
    {"name": "UTC+6", "offset": 6, "tz": "Asia/Almaty"},
    {"name": "UTC+7", "offset": 7, "tz": "Asia/Bangkok"},
    {"name": "UTC+8", "offset": 8, "tz": "Asia/Shanghai"},
    {"name": "UTC+9", "offset": 9, "tz": "Asia/Tokyo"},
    {"name": "UTC+10", "offset": 10, "tz": "Australia/Sydney"},
    {"name": "UTC+11", "offset": 11, "tz": "Pacific/Norfolk"},
    {"name": "UTC+12", "offset": 12, "tz": "Pacific/Auckland"},
    {"name": "UTC-1", "offset": -1, "tz": "Atlantic/Azores"},
    {"name": "UTC-2", "offset": -2, "tz": "America/Noronha"},
    {"name": "UTC-3", "offset": -3, "tz": "America/Sao_Paulo"},
    {"name": "UTC-4", "offset": -4, "tz": "America/New_York"},
    {"name": "UTC-5", "offset": -5, "tz": "America/Chicago"},
    {"name": "UTC-6", "offset": -6, "tz": "America/Denver"},
    {"name": "UTC-7", "offset": -7, "tz": "America/Los_Angeles"},
    {"name": "UTC-8", "offset": -8, "tz": "America/Anchorage"},
    {"name": "UTC-9", "offset": -9, "tz": "Pacific/Gambier"},
    {"name": "UTC-10", "offset": -10, "tz": "Pacific/Honolulu"},
    {"name": "UTC-11", "offset": -11, "tz": "Pacific/Midway"},
]

UTC_TIMEZONES.sort(key=lambda x: (x["offset"] < 0, abs(x["offset"]), x["offset"]))

@dataclass
class UserSettings:
    user_id: int
    daily_reminders: bool = True
    event_reminders: bool = True
    morning_time: str = "07:00"
    evening_time: str = "21:00"
    event_reminder_minutes: int = 20
    timezone: str = "Europe/London"
    course_code: str = "BS1"
    created_at: str = None
    updated_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    def get_timezone(self) -> ZoneInfo:
        """Get timezone object, fallback to UTC if invalid"""
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            logger.warning(f"Invalid timezone {self.timezone} for user {self.user_id}, using UTC")
            return ZoneInfo("UTC")

class UserSettingsManager:
    def __init__(self, mongodb_uri: str = None):
        """Initialize with MongoDB connection"""
        if mongodb_uri is None:
            mongodb_uri = os.getenv("MONGODB_URI")
        
        if not mongodb_uri:
            raise ValueError("MONGODB_URI environment variable not set")
        
        try:
            self.client = MongoClient(mongodb_uri)
            self.db = self.client.get_database("campus_genius_bot")
            self.collection = self.db.user_settings
            
            # Create index on user_id for faster queries
            self.collection.create_index("user_id", unique=True)
            
            logger.info("Connected to MongoDB successfully")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        
        self.settings: Dict[int, UserSettings] = {}
        self.load_settings()
    
    def load_settings(self):
        """Load all user settings from MongoDB into memory"""
        try:
            documents = self.collection.find()
            
            for doc in documents:
                user_id = doc['user_id']
                # Remove MongoDB's _id field
                doc.pop('_id', None)
                
                self.settings[user_id] = UserSettings(**doc)
            
            logger.info(f"Loaded settings for {len(self.settings)} users from MongoDB")
        except Exception as e:
            logger.error(f"Failed to load settings from MongoDB: {e}")
            self.settings = {}
    
    def save_settings(self):
        """Legacy method for compatibility - individual saves happen in update_user_setting"""
        pass
    
    def _save_user_to_db(self, settings: UserSettings):
        """Save a single user's settings to MongoDB"""
        try:
            settings_dict = asdict(settings)
            
            self.collection.update_one(
                {"user_id": settings.user_id},
                {"$set": settings_dict},
                upsert=True
            )
            
            logger.debug(f"Saved settings for user {settings.user_id} to MongoDB")
        except Exception as e:
            logger.error(f"Failed to save settings to MongoDB: {e}")
    
    def get_user_settings(self, user_id: int, auto_detect_timezone: bool = True) -> UserSettings:
        """Get settings for a user, create default if not exists"""
        if user_id not in self.settings:
            default_tz = "Europe/London"
            
            self.settings[user_id] = UserSettings(
                user_id=user_id,
                timezone=default_tz,
                course_code="BS1",
                daily_reminders=True,
                event_reminders=True
            )
            self._save_user_to_db(self.settings[user_id])
        
        return self.settings[user_id]
    
    def update_user_setting(self, user_id: int, **kwargs):
        """Update specific user settings"""
        settings = self.get_user_settings(user_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        settings.updated_at = datetime.now().isoformat()
        
        # Save to MongoDB immediately
        self._save_user_to_db(settings)
        logger.info(f"Updated settings for user {user_id}: {kwargs}")
    
    def get_users_with_daily_reminders(self) -> List[UserSettings]:
        """Get all users with daily reminders enabled"""
        return [settings for settings in self.settings.values() if settings.daily_reminders]
    
    def get_users_with_event_reminders(self) -> List[UserSettings]:
        """Get all users with event reminders enabled"""
        return [settings for settings in self.settings.values() if settings.event_reminders]
    
    def is_valid_timezone(self, timezone_str: str) -> bool:
        """Check if timezone string is valid"""
        try:
            ZoneInfo(timezone_str)
            return True
        except Exception:
            return False
    
    def get_common_timezones(self) -> List[dict]:
        """Get list of UTC-based timezones for UI"""
        return UTC_TIMEZONES
    
    def get_timezone_page(self, page: int = 0, per_page: int = 5) -> tuple[List[dict], int, bool, bool]:
        """Get timezone page with pagination info"""
        total_timezones = len(UTC_TIMEZONES)
        total_pages = (total_timezones + per_page - 1) // per_page
        
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, total_timezones)
        
        page_timezones = UTC_TIMEZONES[start_idx:end_idx]
        
        has_prev = page > 0
        has_next = page < total_pages - 1
        
        return page_timezones, total_pages, has_prev, has_next
    
    def detect_user_timezone_from_telegram(self, user) -> str:
        """Try to detect user timezone from Telegram data"""
        return "Europe/London"
    
    def search_timezones(self, query: str, limit: int = 10) -> List[dict]:
        """Search for timezones matching query"""
        query_lower = query.lower()
        matches = []
        
        for tz_info in UTC_TIMEZONES:
            if query_lower in tz_info["name"].lower() or query_lower in tz_info["tz"].lower():
                matches.append(tz_info)
                if len(matches) >= limit:
                    break
        
        return matches
    
    def is_valid_course(self, course_code: str) -> bool:
        """Check if course code is valid"""
        return course_code in ["BS1"]
    
    def get_available_courses(self) -> List[dict]:
        """Get available course codes and names"""
        return [
            {"code": "BS1", "name": "Bachelor of Science in Business Studies (Year 1)"}
        ]

# Global settings manager instance
settings_manager = UserSettingsManager()
