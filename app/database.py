import os
from pathlib import Path
from datetime import datetime
from sqlalchemy import Boolean, create_engine, Column, Integer, String, DateTime, Text, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('SENATE_WIRE_DATABASE_URL') or f"sqlite:///{BASE_DIR / 'data' / 'senate_wire.db'}"

engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class SourceSnapshot(Base):
    __tablename__ = 'source_snapshots'

    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String, nullable=False)
    source_url = Column(String, unique=True, nullable=False)
    content_hash = Column(String, nullable=False)
    extracted_text = Column(Text, nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CachedSource(Base):
    __tablename__ = 'cached_sources'

    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String, unique=True, nullable=False, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String, default='unknown', nullable=False)
    payload_json = Column(Text, default='{}', nullable=False)
    error_message = Column(Text, nullable=True)
    stale = Column(Boolean, default=False, nullable=False)


class Alert(Base):
    __tablename__ = 'alerts'

    id = Column(Integer, primary_key=True, index=True)
    alert_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    source_name = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    trigger_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Subscriber(Base):
    __tablename__ = 'alert_subscribers'

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    confirmed = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    unsubscribe_token = Column(String, unique=True, nullable=False, index=True)
    preferences_json = Column(Text, nullable=False)
    last_alert_sent_at = Column(DateTime, nullable=True)


class AlertEvent(Base):
    __tablename__ = 'alert_events'

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    urgency = Column(String, nullable=False)
    coverage_type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    event_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    dedupe_key = Column(String, unique=True, nullable=False, index=True)


class SentAlert(Base):
    __tablename__ = 'sent_alerts'

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, nullable=False, index=True)
    subscriber_id = Column(Integer, nullable=False, index=True)
    dedupe_key = Column(String, nullable=False, index=True)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    recipient_count = Column(Integer, default=1, nullable=False)


def init_db() -> None:
    (BASE_DIR / 'data').mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)

    if 'alerts' in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM alerts'))

        existing_alert_columns = [column['name'] for column in inspector.get_columns('alerts')]
        needed_alert_columns = [
            'alert_type', 'title', 'body', 'source_name', 'source_url', 'trigger_text', 'created_at'
        ]
        with engine.begin() as conn:
            for column in needed_alert_columns:
                if column not in existing_alert_columns:
                    conn.execute(text(f'ALTER TABLE alerts ADD COLUMN {column} VARCHAR'))

    if 'source_snapshots' in inspector.get_table_names():
        existing_snapshot_columns = [column['name'] for column in inspector.get_columns('source_snapshots')]
        needed_snapshot_columns = [
            'source_name', 'source_url', 'content_hash', 'extracted_text', 'checked_at'
        ]
        with engine.begin() as conn:
            for column in needed_snapshot_columns:
                if column not in existing_snapshot_columns:
                    column_type = 'TEXT' if column == 'extracted_text' else 'VARCHAR'
                    conn.execute(text(f'ALTER TABLE source_snapshots ADD COLUMN {column} {column_type}'))

    if 'cached_sources' in inspector.get_table_names():
        existing_cache_columns = [column['name'] for column in inspector.get_columns('cached_sources')]
        needed_cache_columns = {
            'source_name': 'VARCHAR',
            'fetched_at': 'DATETIME',
            'status': 'VARCHAR',
            'payload_json': 'TEXT',
            'error_message': 'TEXT',
            'stale': 'BOOLEAN',
        }
        with engine.begin() as conn:
            for column, column_type in needed_cache_columns.items():
                if column not in existing_cache_columns:
                    conn.execute(text(f'ALTER TABLE cached_sources ADD COLUMN {column} {column_type}'))

