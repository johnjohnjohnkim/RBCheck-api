from datetime import date, datetime, time, timedelta, timezone

from ..config import env


def today(now: datetime | None = None) -> date:
    """Today's date in the app's time zone, whatever zone the server runs in."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(env.tz).date()


def local_date(dt: datetime) -> date:
    """The calendar day of a stored timestamp in the app's time zone."""
    return dt.astimezone(env.tz).date()


def day_range(first: date, last: date | None = None) -> tuple[datetime, datetime]:
    """
    The span from the start of `first` to the start of the day after `last`
    (or after `first` alone), in the app's time zone. Filter with
    start <= t < end so a moment is never in two days.
    """
    last = last or first
    start = datetime.combine(first, time.min, env.tz)
    end = datetime.combine(last + timedelta(days=1), time.min, env.tz)
    return start, end


SETTLE_HOURS = 2


def settled(day: date, now: datetime | None = None) -> bool:
    """True once a day has been over long enough that its texts have been
    ingested; only then is its stored digest treated as final."""
    now = now or datetime.now(timezone.utc)
    return now >= day_range(day)[1] + timedelta(hours=SETTLE_HOURS)
