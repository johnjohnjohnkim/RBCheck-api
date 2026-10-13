from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import demo, models
from app.database import engine, make_engine

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
REAL_PLACES = ["UCC TIM'S UPPER", "DALDONGNAE LONDON", "KREAM PANTRY", "SHOPPERS DRUG MART #0848"]


def real_rows(n=200):
    return [{
        "transaction_id": 1000 + i,
        "transaction_datetime": NOW - timedelta(hours=7 * i),
        "amount": Decimal("12.34") + i,
        "place": REAL_PLACES[i % len(REAL_PLACES)] if i % 5 else "",
        "transaction_type": "Withdrawal" if i % 5 == 0 else "CC Purchase",
    } for i in range(n)]


def test_scramble_hides_the_real_data():
    rows = real_rows()
    out = demo.scramble(rows, "secret", NOW)

    assert 0.7 * len(rows) < len(out) < 0.9 * len(rows)            # some are left out
    assert not {r["place"] for r in out} & set(REAL_PLACES)         # no real merchant names
    assert {r["place"] for r in out if r["transaction_type"] == "Withdrawal"} == {""}  # blanks stay blank
    same = [{**r, "amount": Decimal("50.00")} for r in rows]
    amounts = [r["amount"] for r in demo.scramble(same, "secret", NOW)]
    assert len(set(amounts)) > 0.9 * len(amounts) and amounts.count(Decimal("50.00")) <= 1  # real amounts don't survive
    assert all(r["transaction_datetime"] <= NOW for r in out)
    assert [r["transaction_id"] for r in out] == list(range(1, len(out) + 1))
    assert out == sorted(out, key=lambda r: r["transaction_datetime"])


def test_scramble_is_stable_for_one_secret_and_different_for_another():
    rows = real_rows()
    assert demo.scramble(rows, "secret", NOW) == demo.scramble(rows, "secret", NOW)
    assert demo.scramble(rows, "secret", NOW) != demo.scramble(rows, "other", NOW)


def test_one_real_merchant_always_gets_the_same_stand_in():
    rows = [r for r in real_rows() if r["place"] == "KREAM PANTRY"]
    assert len({r["place"] for r in demo.scramble(rows, "secret", NOW)}) == 1


def test_amounts_and_times_stay_in_range():
    rows = real_rows()
    for r in demo.scramble(rows, "secret", NOW):
        assert r["amount"] >= Decimal("0.01")
    low, high = demo.OVERALL_SCALE[0] * demo.ROW_SCALE[0], demo.OVERALL_SCALE[1] * demo.ROW_SCALE[1]
    total_real = sum(r["amount"] for r in rows)
    total_demo = sum(r["amount"] for r in demo.scramble(rows, "secret", NOW))
    assert Decimal(low) * Decimal("0.5") * total_real < total_demo < Decimal(high) * total_real


@pytest.fixture
def demo_engine():
    demo.ensure_database(engine, "rbcheck_demo_test")
    target = make_engine("rbcheck_demo_test")
    models.Base.metadata.create_all(bind=target)
    yield target
    target.dispose()


def test_refresh_replaces_the_demo_data(db, demo_engine):
    for r in real_rows(50):
        db.add(models.Transaction(**r))
    db.commit()

    first = demo.refresh(engine, demo_engine, "secret", NOW)
    assert first > 0
    with demo_engine.begin() as conn:
        conn.execute(models.Transaction.__table__.insert(), [{"transaction_id": -1, "transaction_datetime": NOW,
                                                              "amount": 1, "place": "VANDAL", "transaction_type": "debit"}])
    assert demo.refresh(engine, demo_engine, "secret", NOW) == first   # a visitor's entry is gone again
    with demo_engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.Transaction.__table__)).scalar() == first
        assert not conn.execute(select(models.Transaction.place).where(models.Transaction.place.in_(REAL_PLACES))).first()
    assert db.query(models.Transaction).count() == 50                   # the real data is untouched


def test_refresh_refuses_to_overwrite_its_source():
    with pytest.raises(ValueError):
        demo.refresh(engine, engine, "secret", NOW)


def test_settings_refuse_a_demo_pointed_at_itself():
    from pydantic import ValidationError
    from app.config import Env

    with pytest.raises(ValidationError):
        Env(DATABASE_NAME="rbcheck", DEMO_SOURCE_DATABASE_NAME="rbcheck")
