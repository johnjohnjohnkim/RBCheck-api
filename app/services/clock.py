from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import env


def app_tz() -> ZoneInfo:
    return ZoneInfo(env.TIMEZONE)


def today(now: datetime | None = None) -> date:
    """Today's date in the app timezone, whatever timezone the server runs in."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(app_tz()).date()


def local_date(dt: datetime) -> date:
    """Calendar day of a stored timestamp in the app timezone.

    Postgres returns aware datetimes; they are converted. Naive ones (SQLite, or
    values not yet round-tripped) are already local wall-clock times.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(app_tz())
    return dt.date()


SETTLE_HOURS = 2


def settled(day: date, now: datetime | None = None) -> bool:
    """True once a day has been over long enough that its texts have been
    ingested; only then is its stored digest treated as final."""
    now = now or datetime.now(timezone.utc)
    day_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=app_tz())
    return now >= day_end + timedelta(hours=SETTLE_HOURS)
