from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.database import CachedSource, SessionLocal


def utcnow() -> datetime:
    return datetime.utcnow()


def _decode_payload(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def upsert_source_success(source_name: str, payload: Dict[str, Any], fetched_at: Optional[datetime] = None) -> None:
    fetched_at = fetched_at or utcnow()
    db = SessionLocal()
    try:
        row = db.query(CachedSource).filter_by(source_name=source_name).first()
        encoded = json.dumps(payload, sort_keys=True, default=str)
        if not row:
            row = CachedSource(source_name=source_name)
            db.add(row)
        row.fetched_at = fetched_at
        row.status = "ok"
        row.payload_json = encoded
        row.error_message = None
        row.stale = False
        db.commit()
    finally:
        db.close()


def upsert_source_failure(source_name: str, error_message: str, fetched_at: Optional[datetime] = None) -> None:
    fetched_at = fetched_at or utcnow()
    db = SessionLocal()
    try:
        row = db.query(CachedSource).filter_by(source_name=source_name).first()
        if not row:
            row = CachedSource(source_name=source_name, payload_json="{}")
            db.add(row)
        row.fetched_at = fetched_at
        row.status = "error"
        row.error_message = (error_message or "source fetch failed")[:2000]
        row.stale = bool(row.payload_json and row.payload_json != "{}")
        db.commit()
    finally:
        db.close()


def get_source_snapshot(source_name: str, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        row = db.query(CachedSource).filter_by(source_name=source_name).first()
        if not row:
            return None
        payload = _decode_payload(row.payload_json)
        is_stale = bool(row.stale)
        if max_age_seconds and row.fetched_at:
            is_stale = is_stale or row.fetched_at < utcnow() - timedelta(seconds=max_age_seconds)
        return {
            "source_name": row.source_name,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            "status": row.status,
            "payload": payload,
            "error_message": row.error_message,
            "stale": is_stale,
        }
    finally:
        db.close()


def get_source_text(source_name: str, default: str = "") -> str:
    snapshot = get_source_snapshot(source_name)
    if not snapshot:
        return default
    payload = snapshot.get("payload") or {}
    text = payload.get("text")
    return text if isinstance(text, str) else default


def source_status_summary() -> Dict[str, Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(CachedSource).all()
        return {
            row.source_name: {
                "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
                "status": row.status,
                "error_message": row.error_message,
                "stale": bool(row.stale),
            }
            for row in rows
        }
    finally:
        db.close()
