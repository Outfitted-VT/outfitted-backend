"""IANA timezone helpers. Unknown names fall back to UTC, so a bad stored value never breaks a request."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def zone(name: str | None) -> ZoneInfo:
    return ZoneInfo(name) if name and is_valid_timezone(name) else ZoneInfo("UTC")


def local_now(now: datetime, name: str | None) -> datetime:
    return now.astimezone(zone(name))


def next_midnight(day: date, name: str | None) -> datetime:
    """The UTC instant the local day after `day` begins."""
    return datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone(name)).astimezone(UTC)
