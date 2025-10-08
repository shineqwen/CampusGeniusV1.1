from datetime import datetime
from zoneinfo import ZoneInfo
from functools import lru_cache
import re
from typing import Dict, Any, Optional

# Pre-compiled regex for better performance
RFC3339_REGEX = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|([+-]\d{2}):?(\d{2}))$')

@lru_cache(maxsize=100)
def _parse_rfc3339_cached(dt_str: str) -> datetime:
    """Cached RFC3339 parser for better performance"""
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)

def _parse_rfc3339(dt_str: str) -> datetime:
    """Fast RFC3339 parser with caching"""
    return _parse_rfc3339_cached(dt_str)

class EventFormatter:
    """Event formatter with optimized string operations"""
    
    def __init__(self):
        # Pre-compiled format strings for better performance
        self.time_format = "<b>%H:%M–%H:%M</b>"
        self.all_day_format = "<b>All-day</b>"
        
    def _format_time_range(self, start_dt: datetime, end_dt: datetime) -> str:
        """Optimized time range formatting"""
        if start_dt.date() == end_dt.date():
            return f"<b>{start_dt:%H:%M}–{end_dt:%H:%M}</b>"
        else:
            return f"<b>{start_dt:%H:%M} ({start_dt:%d %b})–{end_dt:%H:%M} ({end_dt:%d %b})</b>"
    
    def _extract_event_data(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and normalize event data efficiently"""
        return {
            'summary': event.get("summary") or "(No title)",
            'location': event.get("location"),
            'start': event.get("start", {}),
            'end': event.get("end", {}),
            'hangout': event.get("hangoutLink") or (
                event.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri")
            )
        }
    
    def format_single_event(self, event: Dict[str, Any], tz: ZoneInfo) -> str:
        """Format a single event optimized for performance"""
        data = self._extract_event_data(event)
        
        # Format time
        if "dateTime" in data['start']:
            s = _parse_rfc3339(data['start']["dateTime"]).astimezone(tz)
            e = _parse_rfc3339(data['end'].get("dateTime", data['start']["dateTime"])).astimezone(tz)
            time_str = self._format_time_range(s, e)
        else:
            time_str = self.all_day_format
        
        # Build block efficiently using list comprehension
        parts = [f"{time_str}", f"📚 <i>{data['summary']}</i>"]
        
        if data['location']:
            parts.append(f"📍 {data['location']}")
        
        if data['hangout']:
            parts.append(f"🔗 <a href='{data['hangout']}'>Join meeting</a>")
        
        return "\n".join(parts)

def format_agenda(events: list[dict], tz: ZoneInfo) -> str:
    """Optimized agenda formatting"""
    if not events:
        return "• <i>No events — your schedule is wide open. 🧘</i>"
    
    formatter = EventFormatter()
    
    # Use list comprehension for better performance
    blocks = [formatter.format_single_event(event, tz) for event in events]
    
    return "\n\n".join(blocks)

def format_agenda_batch(events_by_date: Dict[str, list[dict]], tz: ZoneInfo) -> Dict[str, str]:
    """Format multiple days' agendas at once"""
    formatter = EventFormatter()
    results = {}
    
    for date_str, events in events_by_date.items():
        if not events:
            results[date_str] = "• <i>No events — your schedule is wide open. 🧘</i>"
        else:
            blocks = [formatter.format_single_event(event, tz) for event in events]
            results[date_str] = "\n\n".join(blocks)
    
    return results

# Utility function for clearing caches
def clear_format_cache():
    """Clear formatting caches"""
    _parse_rfc3339_cached.cache_clear()