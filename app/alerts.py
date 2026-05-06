from __future__ import annotations

import json
import os
import re
import secrets
import smtplib
from dataclasses import asdict
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, Iterable, Optional

from app.database import AlertEvent, SentAlert, SessionLocal, Subscriber

DEFAULT_ALERT_PREFERENCES = {
    "votes": True,
    "schedule_changes": True,
    "media_events": True,
    "committee_hearings": False,
    "daily_digest": False,
}

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
SIGNUP_RATE_LIMIT: Dict[str, list[datetime]] = {}


def normalize_email(email: str) -> Optional[str]:
    normalized = (email or "").strip().lower()
    if not normalized or len(normalized) > 254 or not EMAIL_RE.match(normalized):
        return None
    return normalized


def smtp_configured() -> bool:
    return all(os.getenv(name) for name in ["SMTP_HOST", "SMTP_PORT", "SMTP_FROM_EMAIL"])


def smtp_status() -> Dict[str, Any]:
    return {
        "configured": smtp_configured(),
        "host_present": bool(os.getenv("SMTP_HOST")),
        "port_present": bool(os.getenv("SMTP_PORT")),
        "username_present": bool(os.getenv("SMTP_USERNAME")),
        "from_email_present": bool(os.getenv("SMTP_FROM_EMAIL")),
    }


def allow_signup(remote_addr: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.utcnow()
    key = remote_addr or "unknown"
    recent = [stamp for stamp in SIGNUP_RATE_LIMIT.get(key, []) if (now - stamp).total_seconds() < 300]
    if len(recent) >= 5:
        SIGNUP_RATE_LIMIT[key] = recent
        return False
    recent.append(now)
    SIGNUP_RATE_LIMIT[key] = recent
    return True


def merge_preferences(raw_preferences: Any) -> Dict[str, bool]:
    preferences = dict(DEFAULT_ALERT_PREFERENCES)
    if isinstance(raw_preferences, str) and raw_preferences.strip():
        try:
            raw_preferences = json.loads(raw_preferences)
        except json.JSONDecodeError:
            raw_preferences = {}
    if isinstance(raw_preferences, dict):
        for key in preferences:
            if key in raw_preferences:
                preferences[key] = bool(raw_preferences[key])
    return preferences


def create_or_update_subscriber(email: str, preferences: Dict[str, bool], confirmed: bool) -> Subscriber:
    db = SessionLocal()
    try:
        subscriber = db.query(Subscriber).filter_by(email=email).first()
        if subscriber:
            subscriber.active = True
            subscriber.preferences_json = json.dumps(preferences, sort_keys=True)
            if confirmed:
                subscriber.confirmed = True
            if not subscriber.unsubscribe_token:
                subscriber.unsubscribe_token = secrets.token_urlsafe(32)
        else:
            subscriber = Subscriber(
                email=email,
                confirmed=confirmed,
                active=True,
                unsubscribe_token=secrets.token_urlsafe(32),
                preferences_json=json.dumps(preferences, sort_keys=True),
            )
            db.add(subscriber)
        db.commit()
        db.refresh(subscriber)
        return subscriber
    finally:
        db.close()


def confirm_subscriber(token: str) -> bool:
    db = SessionLocal()
    try:
        subscriber = db.query(Subscriber).filter_by(unsubscribe_token=token).first()
        if not subscriber:
            return False
        subscriber.confirmed = True
        subscriber.active = True
        db.commit()
        return True
    finally:
        db.close()


def unsubscribe(token: str) -> bool:
    db = SessionLocal()
    try:
        subscriber = db.query(Subscriber).filter_by(unsubscribe_token=token).first()
        if not subscriber:
            return False
        subscriber.active = False
        db.commit()
        return True
    finally:
        db.close()


def send_email(to_email: str, subject: str, body: str) -> bool:
    if not smtp_configured():
        return False

    msg = EmailMessage()
    from_email = os.getenv("SMTP_FROM_EMAIL", "")
    from_name = os.getenv("SMTP_FROM_NAME", "Senate JOLT")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True


def send_confirmation_email(email: str, token: str, base_url: str) -> bool:
    confirm_url = f"{base_url.rstrip('/')}/alerts/confirm?token={token}"
    body = (
        "Confirm your Senate JOLT alerts signup:\n\n"
        f"{confirm_url}\n\n"
        "Senate JOLT alerts are compiled from public sources and Gallery-appropriate updates. "
        "You can unsubscribe at any time."
    )
    return send_email(email, "Confirm your Senate JOLT alerts", body)


def parse_event_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def preference_enabled(subscriber: Subscriber, coverage_type: str) -> bool:
    try:
        preferences = json.loads(subscriber.preferences_json or "{}")
    except json.JSONDecodeError:
        preferences = DEFAULT_ALERT_PREFERENCES
    if coverage_type in {"vote_underway", "vote_block_within_60", "expected_vote_block_today"}:
        return bool(preferences.get("votes", True))
    if coverage_type in {"major_schedule_change"}:
        return bool(preferences.get("schedule_changes", True))
    if coverage_type in {"ebb_media_event", "leadership_press_availability"}:
        return bool(preferences.get("media_events", True))
    if coverage_type in {"committee_hearing_within_2"}:
        return bool(preferences.get("committee_hearings", False))
    if coverage_type in {"cloture_filed"}:
        return bool(preferences.get("votes", True))
    return False


def event_from_notification(notification: Any) -> AlertEvent:
    data = asdict(notification) if hasattr(notification, "__dataclass_fields__") else dict(notification)
    db = SessionLocal()
    try:
        event = db.query(AlertEvent).filter_by(dedupe_key=data["dedupe_key"]).first()
        if not event:
            event = AlertEvent(
                title=data.get("title", "Senate JOLT alert"),
                body=data.get("body", "A public Senate coverage signal changed."),
                urgency=data.get("urgency", "medium"),
                coverage_type=data.get("coverage_type", "public_signal"),
                source=data.get("source", "Public source"),
                source_url=data.get("url") or data.get("source_url") or "",
                event_time=parse_event_datetime(data.get("event_time") or data.get("timestamp")),
                expires_at=parse_event_datetime(data.get("expires_at")),
                dedupe_key=data["dedupe_key"],
            )
            db.add(event)
            db.commit()
            db.refresh(event)
        return event
    finally:
        db.close()


def format_alert_email(event: AlertEvent, subscriber: Subscriber, base_url: str) -> tuple[str, str]:
    unsubscribe_url = f"{base_url.rstrip('/')}/alerts/unsubscribe?token={subscriber.unsubscribe_token}"
    subject = f"Senate JOLT: {event.title}"
    event_time = event.event_time.isoformat(timespec="minutes") if event.event_time else "Monitor source for timing."
    body = (
        f"{event.title}\n\n"
        f"What happened: {event.body}\n\n"
        f"Coverage timing: {event_time}\n"
        "Coverage location: Public Senate/Gallery source if posted.\n"
        "Expected next action: Monitor the linked public source for updates.\n"
        f"Source: {event.source}\n{event.source_url}\n\n"
        "Public notice: Senate JOLT alerts are compiled from public sources and Gallery-appropriate updates.\n\n"
        f"Unsubscribe: {unsubscribe_url}\n"
    )
    return subject, body


def deliver_alert_events(notifications: Iterable[Any], base_url: str) -> Dict[str, Any]:
    if not smtp_configured():
        events_created = 0
        for notification in notifications:
            event_from_notification(notification)
            events_created += 1
        return {"email_configured": False, "events_created": events_created, "emails_sent": 0}

    events_created = 0
    emails_sent = 0
    db = SessionLocal()
    try:
        subscribers = db.query(Subscriber).filter_by(active=True, confirmed=True).all()
    finally:
        db.close()

    for notification in notifications:
        event = event_from_notification(notification)
        events_created += 1
        recipient_count = 0
        for subscriber in subscribers:
            if not preference_enabled(subscriber, event.coverage_type):
                continue
            db = SessionLocal()
            try:
                already_sent = db.query(SentAlert).filter_by(subscriber_id=subscriber.id, dedupe_key=event.dedupe_key).first()
                if already_sent:
                    continue
                subject, body = format_alert_email(event, subscriber, base_url)
                if send_email(subscriber.email, subject, body):
                    recipient_count += 1
                    emails_sent += 1
                    db.add(SentAlert(alert_id=event.id, subscriber_id=subscriber.id, dedupe_key=event.dedupe_key, recipient_count=1))
                    db_subscriber = db.query(Subscriber).get(subscriber.id)
                    if db_subscriber:
                        db_subscriber.last_alert_sent_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()
        if recipient_count:
            db = SessionLocal()
            try:
                rows = db.query(SentAlert).filter_by(alert_id=event.id, dedupe_key=event.dedupe_key).all()
                for row in rows:
                    row.recipient_count = recipient_count
                db.commit()
            finally:
                db.close()
    return {"email_configured": True, "events_created": events_created, "emails_sent": emails_sent}


def debug_summary() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        subscriber_count = db.query(Subscriber).filter_by(active=True).count()
        recent_events = db.query(AlertEvent).order_by(AlertEvent.created_at.desc()).limit(10).all()
        last_sent = db.query(SentAlert).order_by(SentAlert.sent_at.desc()).first()
        return {
            "subscriber_count": subscriber_count,
            "email_sending_configured": smtp_configured(),
            "recent_alert_types": [event.coverage_type for event in recent_events],
            "last_sent_timestamp": last_sent.sent_at.isoformat() if last_sent else None,
        }
    finally:
        db.close()
