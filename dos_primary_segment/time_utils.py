"""
Time handling: 24-hour HH:MM format, minute arithmetic, midnight crossover.
"""
import re
from typing import Tuple, Optional

# Time format: HH:MM 24-hour, zero-padded
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_time(s: str) -> Optional[int]:
    """Parse HH:MM or H:MM to minutes since midnight. Returns None if invalid."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    m = TIME_RE.match(s)
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    if h < 0 or h > 23 or mn < 0 or mn > 59:
        return None
    return h * 60 + mn


def format_time(minutes: int) -> str:
    """Minutes since midnight to HH:MM 24-hour. Handles next-day (e.g. 24*60+30 -> 00:30)."""
    if minutes < 0:
        minutes = 0
    minutes = minutes % (24 * 60)
    h, mn = divmod(minutes, 60)
    return f"{h:02d}:{mn:02d}"


def normalize_time_str(s: str) -> Optional[str]:
    """Normalize input time string to HH:MM 24-hour. Returns None if invalid."""
    m = parse_time(s)
    return format_time(m) if m is not None else None


def total_minutes(actual_start_min: int, actual_end_min: int) -> int:
    """Total worked minutes. Handles midnight crossover (end < start => next day)."""
    if actual_end_min >= actual_start_min:
        return actual_end_min - actual_start_min
    return (24 * 60 - actual_start_min) + actual_end_min


def t8_minutes(actual_start_min: int) -> int:
    """Standard OT boundary: actual_start + 480 minutes (8 hours)."""
    return actual_start_min + 480


def lpi_minutes_computed(actual_end_min: int, scheduled_end_min: int) -> int:
    """LPI = max(0, actual_end - scheduled_end). Tolerance: if <= 2 min, treat as 0."""
    raw = actual_end_min - scheduled_end_min
    if raw <= 0:
        return 0
    return 0 if raw <= 2 else raw


def parse_shift_range(s: str) -> Tuple[Optional[int], Optional[int]]:
    """Parse 'HH:MM-HH:MM' to (start_minutes, end_minutes)."""
    if not s or "-" not in s:
        return None, None
    parts = s.strip().split("-", 1)
    if len(parts) != 2:
        return None, None
    start = parse_time(parts[0].strip())
    end = parse_time(parts[1].strip())
    return start, end
