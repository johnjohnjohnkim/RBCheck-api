"""
Daily spending digests: one summary per local calendar day, stored in
daily_digests so the history can be tracked.

Spending follows services/spending.py (card payments and deposits excluded,
refunds subtract). "Day" always means a day in the app timezone.

A stored digest is reused only if it was computed once its day had settled
and with the current payload VERSION; anything else is recomputed,
so late texts, edits and format changes don't leave stale rows behind. "Final"
means the day is over; "settled" means it has also been over for a couple of
hours, long enough for the poller to have ingested its late texts.
"""

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import median

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from . import clock
from .clock import local_date
from .spending import spend_value
from .transaction_services import transactions_between

VERSION = 3                   # bump when the payload shape or maths change
UNUSUAL_LOOKBACK_DAYS = 90
MIN_MERCHANT_HISTORY = 3      # prior purchases needed before "usual" means something
MERCHANT_MULTIPLE = 2         # unusual if above this many times the merchant's median...
MERCHANT_MIN_EXTRA = Decimal(20)   # ...and at least this much above it
NEW_MERCHANT_FLOOR = Decimal(100)  # rare merchants: unusual above this or 4x the overall median
MAX_UNUSUAL = 5
TOP_MERCHANTS = 3
MIN_PROJECTION_DAYS = 3       # completed days needed before a month-end projection is meaningful


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _name(place: str | None) -> str:
    return place or "Unknown"


def _unusual(purchases: list, history: list) -> list[dict]:
    """Today's purchases that are large for the merchant (or for the person)."""
    by_merchant: dict[str, list[Decimal]] = defaultdict(list)
    for row in history:
        by_merchant[_name(row.place)].append(spend_value(row.transaction_type, row.amount))
    overall = median(v for vs in by_merchant.values() for v in vs) if by_merchant else Decimal(0)

    found = []
    for row in purchases:
        amount = spend_value(row.transaction_type, row.amount)
        name = _name(row.place)
        prior = by_merchant.get(name, [])
        reason = None
        if len(prior) >= MIN_MERCHANT_HISTORY:
            usual = median(prior)
            if amount > MERCHANT_MULTIPLE * usual and amount - usual >= MERCHANT_MIN_EXTRA:
                reason = f"{amount / usual:.1f}x your usual ${_money(usual)} at {name}"
        elif amount >= max(NEW_MERCHANT_FLOOR, 4 * overall):
            reason = f"large charge at {name}, which you rarely visit"
        if reason:
            found.append({"transaction_id": row.transaction_id, "place": name,
                          "amount": str(_money(amount)), "reason": reason})
    found.sort(key=lambda f: Decimal(f["amount"]), reverse=True)
    return found[:MAX_UNUSUAL]


def _window_start(day: date) -> date:
    """Earliest day whose transactions a digest for `day` needs."""
    return min(day.replace(day=1), day - timedelta(days=UNUSUAL_LOOKBACK_DAYS))


def load_days(db: Session, first: date, last: date) -> dict[date, list]:
    """Transactions on first..last grouped by local calendar day."""
    by_day: dict[date, list] = defaultdict(list)
    for row in transactions_between(db, first, last):
        by_day[local_date(row.transaction_datetime)].append(row)
    return by_day


def digest_payload(by_day: dict[date, list], day: date, final: bool, settled: bool = False) -> dict:
    """The digest for one day from already-loaded transactions (no database access).
    `final` is False while the day is still in progress; `settled` marks it safe to cache."""
    month_start = day.replace(day=1)

    def net(d: date) -> Decimal:
        return sum((spend_value(r.transaction_type, r.amount) for r in by_day.get(d, [])), Decimal(0))

    spend = net(day)
    avg_previous_7 = sum((net(day - timedelta(days=i)) for i in range(1, 8)), Decimal(0)) / 7
    pct = round(float((spend - avg_previous_7) / avg_previous_7 * 100), 1) if avg_previous_7 > 0 else None

    purchases = [r for r in by_day.get(day, []) if spend_value(r.transaction_type, r.amount) > 0]
    merchants: dict[str, dict] = defaultdict(lambda: {"total": Decimal(0), "count": 0})
    for r in purchases:
        entry = merchants[_name(r.place)]
        entry["total"] += spend_value(r.transaction_type, r.amount)
        entry["count"] += 1
    top = sorted(merchants.items(), key=lambda kv: kv[1]["total"], reverse=True)[:TOP_MERCHANTS]

    month_to_date = sum((net(month_start + timedelta(days=i)) for i in range((day - month_start).days + 1)), Decimal(0))
    # Project from completed days only: a half-finished day would drag the pace
    # down, and on the 1st it would be extrapolated 30x.
    completed = day.day if final else day.day - 1
    projected = None
    if completed >= MIN_PROJECTION_DAYS:
        base = month_to_date if final else month_to_date - spend
        projected = str(_money(base / completed * calendar.monthrange(day.year, day.month)[1]))

    history = [r for d, rs in by_day.items() if d < day for r in rs
               if spend_value(r.transaction_type, r.amount) > 0]

    return {
        "v": VERSION,
        "final": final,
        "settled": settled,
        "day": day.isoformat(),
        "spend": str(_money(spend)),
        "avg_previous_7": str(_money(avg_previous_7)),
        "pct_vs_avg": pct,
        "top_merchants": [{"name": n, "total": str(_money(v["total"])), "count": v["count"]} for n, v in top],
        "month_to_date": str(_money(month_to_date)),
        "projected_month_end": projected,
        "purchase_count": len(purchases),
        "unusual": _unusual(purchases, history),
    }


def compute_digest(db: Session, day: date, final: bool | None = None) -> dict:
    """The digest payload for one day, computed from transactions (nothing stored)."""
    if final is None:
        final = day < clock.today()
    return digest_payload(load_days(db, _window_start(day), day), day, final, final and clock.settled(day))


def _save(db: Session, items: dict[date, tuple[dict, datetime]], existing: dict | None = None) -> None:
    """Upsert digests and commit once. `existing` maps days to rows the caller
    already loaded (saves a query per day). If a concurrent request inserted the
    same day first, the retry looks the rows up afresh and updates them."""
    for attempt in (1, 2):
        for day, (payload, computed_at) in items.items():
            row = existing.get(day) if existing is not None and attempt == 1 else db.get(models.DailyDigest, day)
            if row is None:
                db.add(models.DailyDigest(day=day, payload=payload, computed_at=computed_at))
            else:
                row.payload, row.computed_at = payload, computed_at
        try:
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise


def to_schema(payload: dict, computed_at: datetime) -> schemas.Digest:
    return schemas.Digest(**payload, computed_at=computed_at)


def store_digest(db: Session, day: date) -> schemas.Digest:
    """Compute and save the digest for a day; recomputing replaces it (idempotent)."""
    payload = compute_digest(db, day)
    now = datetime.now(timezone.utc)
    _save(db, {day: (payload, now)})
    return to_schema(payload, now)


def _reusable(row: models.DailyDigest | None) -> bool:
    return row is not None and row.payload.get("v") == VERSION and row.payload.get("settled") is True


def history(db: Session, today: date, days: int) -> list[schemas.Digest]:
    """Digests for the last `days` days, newest first, using a fixed number of
    queries. Settled stored digests are served as they are; today's and any
    missing, unfinished or outdated ones are recomputed from one shared read of
    the transactions. Days before the first transaction are left out."""
    first = db.query(func.min(models.Transaction.transaction_datetime)).scalar()
    if first is None:
        return []
    earliest = local_date(first)
    wanted = [d for d in (today - timedelta(days=i) for i in range(days)) if d >= earliest]
    stored = {r.day: r for r in db.query(models.DailyDigest).filter(models.DailyDigest.day.in_(wanted)).all()}

    entries = {d: (stored[d].payload, stored[d].computed_at) for d in wanted if _reusable(stored.get(d))}
    stale = [d for d in wanted if d not in entries]
    if stale:
        by_day = load_days(db, _window_start(min(stale)), today)
        now = datetime.now(timezone.utc)
        fresh = {d: (digest_payload(by_day, d, final=d < today, settled=d < today and clock.settled(d, now)), now) for d in stale}
        entries.update(fresh)
        _save(db, fresh, existing=stored)
    return [to_schema(*entries[d]) for d in wanted]


def spending_summary(db: Session, today: date) -> schemas.SpendingDisplay:
    """Spend today, this week (from Monday), the last 7 days including today, and this month."""
    starts = {
        "daily": today,
        "weekly": today - timedelta(days=today.weekday()),
        "rolling": today - timedelta(days=6),
        "monthly": today.replace(day=1),
    }
    rows = transactions_between(db, min(starts.values()), today)
    dated = [(local_date(r.transaction_datetime), spend_value(r.transaction_type, r.amount)) for r in rows]
    return schemas.SpendingDisplay(**{
        name: sum((v for d, v in dated if start <= d <= today), Decimal(0))
        for name, start in starts.items()
    })
