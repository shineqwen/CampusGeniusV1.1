import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache
from typing import Optional, Dict, Any, List
import asyncio
import time
import re
from urllib.parse import urlencode
import aiohttp
from icalendar import Calendar, Event

from config import BotConfig
from course_data import FACULTIES

logger = logging.getLogger("alfred.dcu_timetable")

# Flattened course lookup for backward compatibility - built from course_data
COURSES = {}

def _build_course_lookup():
    """Build the flattened COURSES dict from hierarchical structure in course_data"""
    global COURSES
    COURSES.clear()
    
    for faculty_key, faculty_data in FACULTIES.items():
        for course_key, course_data in faculty_data["courses"].items():
            for year, year_data in course_data["years"].items():
                COURSES[year_data["code"]] = {
                    "id": year_data["id"],
                    "name": year_data["name"],
                    "code": year_data["code"],
                    "faculty": faculty_key,
                    "course": course_key,
                    "year": year
                }

# Build the lookup on module load
_build_course_lookup()

# Cache for timetable events with TTL
class TimetableCache:
    def __init__(self, ttl_seconds: int = 900):  # 15 minutes TTL for timetables
        self.cache: Dict[str, tuple[float, list]] = {}
        self.ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[list]:
        if key in self.cache:
            timestamp, events = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return events
            del self.cache[key]
        return None
    
    def set(self, key: str, events: list):
        self.cache[key] = (time.time(), events)
    
    def clear_expired(self):
        current_time = time.time()
        expired_keys = [
            key for key, (timestamp, _) in self.cache.items()
            if current_time - timestamp >= self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]

# Global cache instance
timetable_cache = TimetableCache()

def _parse_icalendar(ics_data: str) -> List[Dict[str, Any]]:
    """Parse iCalendar data and convert to our event format"""
    try:
        cal = Calendar.from_ical(ics_data)
        events = []
        
        for component in cal.walk():
            if component.name == "VEVENT":
                event = {}
                
                # Extract event details
                summary = component.get('SUMMARY')
                if summary:
                    event['summary'] = str(summary)
                
                # Extract start time
                dtstart = component.get('DTSTART')
                if dtstart and hasattr(dtstart, 'dt'):
                    if isinstance(dtstart.dt, datetime):
                        event['start'] = {'dateTime': dtstart.dt.isoformat()}
                    else:
                        # All-day event
                        event['start'] = {'date': dtstart.dt.isoformat()}
                
                # Extract end time
                dtend = component.get('DTEND')
                if dtend and hasattr(dtend, 'dt'):
                    if isinstance(dtend.dt, datetime):
                        event['end'] = {'dateTime': dtend.dt.isoformat()}
                    else:
                        event['end'] = {'date': dtend.dt.isoformat()}
                
                # Extract location
                location = component.get('LOCATION')
                if location:
                    event['location'] = str(location)
                
                # Extract description and parse staff info
                description = component.get('DESCRIPTION')
                if description:
                    desc_str = str(description)
                    # Parse staff information from description
                    staff_match = re.search(r'Staff: (.+?)(?:\n|$)', desc_str)
                    if staff_match:
                        event['staff'] = staff_match.group(1).strip()
                    
                    # Store full description
                    event['description'] = desc_str
                
                # Add unique ID
                uid = component.get('UID')
                if uid:
                    event['id'] = str(uid)
                
                # Add event type based on summary
                if summary:
                    summary_str = str(summary).lower()
                    if 'lecture' in summary_str:
                        event['event_type'] = 'Lecture'
                    elif 'tutorial' in summary_str:
                        event['event_type'] = 'Tutorial'
                    elif 'lab' in summary_str:
                        event['event_type'] = 'Lab'
                    else:
                        event['event_type'] = 'Event'
                
                if 'start' in event:  # Only add if we have a start time
                    events.append(event)
        
        return events
    except Exception as e:
        logger.error(f"Failed to parse iCalendar data: {e}")
        return []

async def _fetch_timetable_data(course_id: str) -> str:
    """Fetch timetable data from DCU API"""
    url = "https://timetable.redbrick.dcu.ie/api"
    params = {"courses": course_id}
    
    timeout = aiohttp.ClientTimeout(total=30)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logger.error(f"Failed to fetch timetable: HTTP {response.status}")
                    return ""
    except Exception as e:
        logger.error(f"Error fetching timetable data: {e}")
        return ""

def _filter_events_for_date(events: List[Dict[str, Any]], target_date: datetime, tz: ZoneInfo) -> List[Dict[str, Any]]:
    """Filter events for a specific date"""
    target_date_local = target_date.astimezone(tz).date()
    filtered_events = []
    
    for event in events:
        start_info = event.get('start', {})
        
        if 'dateTime' in start_info:
            # Timed event
            try:
                event_dt = datetime.fromisoformat(start_info['dateTime'].replace('Z', '+00:00'))
                event_date_local = event_dt.astimezone(tz).date()
                if event_date_local == target_date_local:
                    filtered_events.append(event)
            except Exception as e:
                logger.warning(f"Failed to parse event datetime: {e}")
        elif 'date' in start_info:
            # All-day event
            try:
                event_date = datetime.fromisoformat(start_info['date']).date()
                if event_date == target_date_local:
                    filtered_events.append(event)
            except Exception as e:
                logger.warning(f"Failed to parse event date: {e}")
    
    # Sort by start time
    def sort_key(event):
        start_info = event.get('start', {})
        if 'dateTime' in start_info:
            try:
                return datetime.fromisoformat(start_info['dateTime'].replace('Z', '+00:00'))
            except:
                return datetime.min.replace(tzinfo=ZoneInfo("UTC"))
        else:
            return datetime.min.replace(tzinfo=ZoneInfo("UTC"))
    
    filtered_events.sort(key=sort_key)
    return filtered_events

async def fetch_events_for_date_async(course_code: str, day: datetime, tz: ZoneInfo) -> List[Dict[str, Any]]:
    """Async wrapper for event fetching"""
    return await fetch_events_for_date(course_code, day, tz)

async def fetch_events_for_date(course_code: str, day: datetime, tz: ZoneInfo) -> List[Dict[str, Any]]:
    """Fetch events with caching"""
    if course_code not in COURSES:
        logger.error(f"Unknown course code: {course_code}")
        return []
    
    course_id = COURSES[course_code]["id"]
    
    # Create cache key (cache for the whole course, not per day)
    cache_key = f"timetable_{course_code}_{tz.key}"
    
    # Check cache first
    cached_events = timetable_cache.get(cache_key)
    if cached_events is not None:
        logger.debug(f"Cache hit for {cache_key}")
        # Filter cached events for the specific date
        return _filter_events_for_date(cached_events, day, tz)
    
    try:
        # Fetch fresh timetable data
        ics_data = await _fetch_timetable_data(course_id)
        if not ics_data:
            logger.warning(f"No timetable data received for course {course_code}")
            return []
        
        # Parse iCalendar data
        all_events = _parse_icalendar(ics_data)
        
        # Cache the full timetable
        timetable_cache.set(cache_key, all_events)
        logger.debug(f"Cached {len(all_events)} events for course {course_code}")
        
        # Return filtered events for the requested date
        return _filter_events_for_date(all_events, day, tz)
        
    except Exception as e:
        logger.error(f"Failed to fetch timetable for {course_code}: {e}")
        return []

async def fetch_events_batch(course_code: str, days: List[datetime], tz: ZoneInfo) -> Dict[str, List[Dict[str, Any]]]:
    """Batch fetch events for multiple days"""
    if course_code not in COURSES:
        logger.error(f"Unknown course code: {course_code}")
        return {day.date().isoformat(): [] for day in days}
    
    course_id = COURSES[course_code]["id"]
    cache_key = f"timetable_{course_code}_{tz.key}"
    
    # Check cache first
    cached_events = timetable_cache.get(cache_key)
    if cached_events is None:
        # Fetch fresh data if not cached
        try:
            ics_data = await _fetch_timetable_data(course_id)
            if ics_data:
                cached_events = _parse_icalendar(ics_data)
                timetable_cache.set(cache_key, cached_events)
                logger.debug(f"Cached {len(cached_events)} events for course {course_code}")
            else:
                cached_events = []
        except Exception as e:
            logger.error(f"Failed to fetch timetable for batch request: {e}")
            cached_events = []
    
    # Filter events for each requested day
    results = {}
    for day in days:
        day_events = _filter_events_for_date(cached_events, day, tz)
        results[day.date().isoformat()] = day_events
    
    return results

# Public API functions - these import from course_data
def get_available_courses() -> Dict[str, Dict[str, str]]:
    """Get list of available courses (flattened)"""
    return COURSES

def get_faculties() -> Dict[str, Dict[str, Any]]:
    """Get hierarchical faculty structure from course_data"""
    return FACULTIES

def get_faculty_courses(faculty_key: str) -> Optional[Dict[str, Any]]:
    """Get courses for a specific faculty"""
    return FACULTIES.get(faculty_key, {}).get("courses")

def get_course_years(faculty_key: str, course_key: str) -> Optional[Dict[int, Any]]:
    """Get available years for a specific course"""
    faculty = FACULTIES.get(faculty_key)
    if faculty:
        course = faculty.get("courses", {}).get(course_key)
        if course:
            return course.get("years")
    return None

def refresh_course_lookup():
    """Refresh the flattened course lookup from course_data"""
    _build_course_lookup()
    logger.info(f"Refreshed course lookup - {len(COURSES)} courses available")

def add_course(code: str, course_id: str, name: str):
    """Legacy function - adds to runtime COURSES dict only"""
    COURSES[code] = {
        "id": course_id,
        "name": name,
        "code": code
    }
    logger.info(f"Added runtime course: {code} - {name}")

def clear_expired_cache():
    """Clear expired cache entries"""
    timetable_cache.clear_expired()

def clear_all_cache():
    """Clear all cache entries"""
    timetable_cache.cache.clear()

# Utility function to validate course exists
def is_valid_course(course_code: str) -> bool:
    """Check if course code is valid"""
    return course_code in COURSES

def get_course_info(course_code: str) -> Optional[Dict[str, str]]:
    """Get course information"""
    return COURSES.get(course_code)

# Statistics functions
def get_course_statistics() -> Dict[str, Any]:
    """Get statistics about available courses"""
    from course_data import get_total_courses, get_all_course_codes
    
    return {
        "total_faculties": len(FACULTIES),
        "total_courses": get_total_courses(),
        "total_course_codes": len(COURSES),
        "available_codes": get_all_course_codes()
    }