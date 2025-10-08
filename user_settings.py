import json
import logging
import os
import subprocess
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from zoneinfo import ZoneInfo

logger = logging.getLogger("alfred.user_settings")

# UTC-based timezone choices
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
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            logger.warning(f"Invalid timezone {self.timezone} for user {self.user_id}, using UTC")
            return ZoneInfo("UTC")

class UserSettingsManager:
    def __init__(self, settings_file: str = "user_settings.json"):
        self.settings_file = settings_file
        self.settings: Dict[int, UserSettings] = {}
        self.auto_commit = os.getenv("AUTO_COMMIT_DATA", "false").lower() == "true"
        self.load_settings()
    
    def _git_commit_and_push(self):
        """Commit settings file to git (if AUTO_COMMIT_DATA is enabled)"""
        if not self.auto_commit:
            return
        
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            logger.warning("GITHUB_TOKEN not set - cannot auto-commit")
            return
        
        try:
            # Set up git credentials using token
            github_repo = os.getenv("GITHUB_REPO", "")
            if github_repo:
                # Replace https:// with https://TOKEN@
                auth_repo = github_repo.replace("https://", f"https://{github_token}@")
                subprocess.run(["git", "remote", "set-url", "origin", auth_repo], check=False)
            
            # Configure git
            subprocess.run(["git", "config", "user.name", "Railway Bot"], check=False)
            subprocess.run(["git", "config", "user.email", "bot@railway.app"], check=False)
            
            # Check if there are changes
            result = subprocess.run(["git", "status", "--porcelain", self.settings_file], 
                                  capture_output=True, text=True, check=False)
            
            if not result.stdout.strip():
                logger.debug("No changes to commit")
                return
            
            # Add, commit, and push
            subprocess.run(["git", "add", self.settings_file], check=True)
            subprocess.run(["git", "commit", "-m", f"Auto-update user settings - {datetime.now().isoformat()}"], check=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)
            
            logger.info("Settings committed to git successfully")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Git command failed: {e}")
        except Exception as e:
            logger.warning(f"Failed to commit settings to git: {e}")
    
    def load_settings(self):
        """Load user settings from file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for user_id_str, settings_dict in data.items():
                        user_id = int(user_id_str)
                        if 'course_code' not in settings_dict:
                            settings_dict['course_code'] = 'BS1'
                        if 'daily_reminders' not in settings_dict:
                            settings_dict['daily_reminders'] = True
                        if 'event_reminders' not in settings_dict:
                            settings_dict['event_reminders'] = True
                        self.settings[user_id] = UserSettings(**settings_dict)
                logger.info(f"Loaded settings for {len(self.settings)} users")
            else:
                logger.info("No settings file found, starting fresh")
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            self.settings = {}
    
    def save_settings(self):
        """Save user settings to file"""
        try:
            data = {}
            for user_id, settings in self.settings.items():
                data[str(user_id)] = asdict(settings)
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved settings for {len(self.settings)} users")
            
            # Auto-commit if enabled
            self._git_commit_and_push()
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
    
    def get_user_settings(self, user_id: int, auto_detect_timezone: bool = True) -> UserSettings:
        if user_id not in self.settings:
            default_tz = "Europe/London"
            
            self.settings[user_id] = UserSettings(
                user_id=user_id,
                timezone=default_tz,
                course_code="BS1",
                daily_reminders=True,
                event_reminders=True
            )
            self.save_settings()
        return self.settings[user_id]
    
    def update_user_setting(self, user_id: int, **kwargs):
        settings = self.get_user_settings(user_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        settings.updated_at = datetime.now().isoformat()
        self.save_settings()
        logger.info(f"Updated settings for user {user_id}: {kwargs}")
    
    def get_users_with_daily_reminders(self) -> List[UserSettings]:
        return [settings for settings in self.settings.values() if settings.daily_reminders]
    
    def get_users_with_event_reminders(self) -> List[UserSettings]:
        return [settings for settings in self.settings.values() if settings.event_reminders]
    
    def is_valid_timezone(self, timezone_str: str) -> bool:
        try:
            ZoneInfo(timezone_str)
            return True
        except Exception:
            return False
    
    def get_common_timezones(self) -> List[dict]:
        return UTC_TIMEZONES
    
    def get_timezone_page(self, page: int = 0, per_page: int = 5) -> tuple[List[dict], int, bool, bool]:
        total_timezones = len(UTC_TIMEZONES)
        total_pages = (total_timezones + per_page - 1) // per_page
        
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, total_timezones)
        
        page_timezones = UTC_TIMEZONES[start_idx:end_idx]
        
        has_prev = page > 0
        has_next = page < total_pages - 1
        
        return page_timezones, total_pages, has_prev, has_next
    
    def detect_user_timezone_from_telegram(self, user) -> str:
        return "Europe/London"
    
    def search_timezones(self, query: str, limit: int = 10) -> List[dict]:
        query_lower = query.lower()
        matches = []
        
        for tz_info in UTC_TIMEZONES:
            if query_lower in tz_info["name"].lower() or query_lower in tz_info["tz"].lower():
                matches.append(tz_info)
                if len(matches) >= limit:
                    break
        
        return matches
    
    def is_valid_course(self, course_code: str) -> bool:
        return course_code in ["BS1"]
    
    def get_available_courses(self) -> List[dict]:
        return [
            {"code": "BS1", "name": "Bachelor of Science in Business Studies (Year 1)"}
        ]

settings_manager = UserSettingsManager()
