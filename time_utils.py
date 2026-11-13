"""Persisted UTC/offset timestamps, formatted consistently in Philippine time."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
PH=ZoneInfo('Asia/Manila')
def transaction_time(value):
    if not value:return 'Not recorded'
    try:
        dt=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(PH).strftime('%b %d, %Y · %I:%M %p PHT')
    except (ValueError,TypeError):return 'Date unavailable'
