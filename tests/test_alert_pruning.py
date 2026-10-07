from __future__ import annotations

from datetime import datetime, timedelta

from app.alerts import prune_old_alert_events
from app.database import AlertEvent, SessionLocal

import pytest

TEST_KEYS = ("prune-fresh", "prune-expired", "prune-ancient", "prune-keep")


@pytest.fixture(autouse=True)
def _clean_test_events():
    db = SessionLocal()
    try:
        db.query(AlertEvent).filter(AlertEvent.dedupe_key.in_(TEST_KEYS)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(AlertEvent).filter(AlertEvent.dedupe_key.in_(TEST_KEYS)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_event(dedupe_key: str, created_days_ago: int = 0, expired: bool = False) -> None:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(AlertEvent(
            title="t", body="b", urgency="low", coverage_type="public_signal",
            source="test", source_url="",
            created_at=now - timedelta(days=created_days_ago),
            expires_at=(now - timedelta(days=1)) if expired else (now + timedelta(days=1)),
            dedupe_key=dedupe_key,
        ))
        db.commit()
    finally:
        db.close()


def _count() -> int:
    db = SessionLocal()
    try:
        return db.query(AlertEvent).count()
    finally:
        db.close()


def test_prune_removes_expired_and_ancient_events():
    _make_event("prune-fresh")
    _make_event("prune-expired", expired=True)
    _make_event("prune-ancient", created_days_ago=45)

    removed = prune_old_alert_events(older_than_days=30)

    assert removed == 2
    assert _count() == 1
    db = SessionLocal()
    try:
        remaining = db.query(AlertEvent).all()
        assert [e.dedupe_key for e in remaining] == ["prune-fresh"]
    finally:
        db.close()


def test_prune_keeps_recent_unexpired_events():
    _make_event("prune-keep", created_days_ago=5)
    assert prune_old_alert_events(older_than_days=30) == 0
    assert _count() == 1
