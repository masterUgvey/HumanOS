from __future__ import annotations
from datetime import datetime
import re

# Timezone-agnostic approach: we operate on naive local datetimes and avoid auto-generated times
# Date-only is always represented as 'YYYY-MM-DD 00:00:00'

DATE_ONLY_FMT = "%Y-%m-%d"
DATETIME_FMT_MIN = "%Y-%m-%d %H:%M"
DATETIME_FMT_SEC = "%Y-%m-%d %H:%M:%S"

def today_deadline_str() -> str:
    """Return today's local date as 'YYYY-MM-DD 00:00:00'."""
    return datetime.now().strftime(f"{DATE_ONLY_FMT} 00:00:00")


def normalize_user_deadline_input(text: str) -> str:
    """Normalize user input into DB string.
    Accepts:
    - 'DD.MM.YY'
    - 'DD.MM.YY HH:MM'
    Returns:
    - 'YYYY-MM-DD 00:00:00' for date-only
    - 'YYYY-MM-DD HH:MM' for date+time
    Raises ValueError on invalid or past date/time.
    """
    s = text.strip()
    if not s:
        raise ValueError("empty")
    s_norm = s.replace('/', '.').replace('-', '.')
    now = datetime.now()
    if ' ' in s_norm and ':' in s_norm:
        dt = datetime.strptime(s_norm, "%d.%m.%y %H:%M")
        if dt < now:
            raise ValueError("past datetime")
        return dt.strftime(DATETIME_FMT_MIN)
    else:
        d = datetime.strptime(s_norm, "%d.%m.%y")
        # date-only allowed if not in the past relative to end-of-day
        end_of_day = d.replace(hour=23, minute=59)
        if end_of_day < now:
            raise ValueError("past date")
        return d.strftime(f"{DATE_ONLY_FMT} 00:00:00")


def is_date_like(text: str) -> bool:
    if text is None:
        return False
    t = str(text).strip()
    if not t:
        return False
    patterns = [
        r"^\d{4}-\d{2}-\d{2}$",
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
        r"^\d{2}\.\d{2}\.\d{2}$",
        r"^\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}$",
    ]
    return any(re.fullmatch(p, t) for p in patterns)


def comment_should_be_saved(text: str, deadline: str | None) -> bool:
    if text is None:
        return False
    t = text.strip()
    if not t:
        return False
    if deadline and t == str(deadline).strip():
        return False
    if is_date_like(t):
        return False
    return True


def format_deadline_for_display(deadline: str | None) -> str:
    """Format deadline from DB for human-readable rendering."""
    if not deadline:
        return "без даты и времени"
    s = str(deadline).strip()
    try:
        if ':' in s:
            # try with seconds, then minutes
            try:
                d = datetime.strptime(s, DATETIME_FMT_SEC)
            except ValueError:
                d = datetime.strptime(s, DATETIME_FMT_MIN)
            if d.hour == 0 and d.minute == 0:
                return f"{d.strftime('%d.%m.%y')} (без времени)"
            return d.strftime('%d.%m.%y %H:%M')
        else:
            d = datetime.strptime(s, DATE_ONLY_FMT)
            return f"{d.strftime('%d.%m.%y')} (без времени)"
    except Exception:
        return "без даты и времени"
