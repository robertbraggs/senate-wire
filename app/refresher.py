from __future__ import annotations

import asyncio
import importlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from app.source_cache import upsert_source_failure, upsert_source_success

USER_AGENT = "Mozilla/5.0 TheSenateJOLT/8.2"


@dataclass(frozen=True)
class SourceConfig:
    name: str
    url: str
    interval_seconds: int
    timeout_seconds: float


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def default_source_configs() -> list[SourceConfig]:
    default_interval = _env_int("SOURCE_REFRESH_INTERVAL_SECONDS", 300)
    timeout = _env_float("SOURCE_HTTP_TIMEOUT_SECONDS", 12.0)
    sources = {
        "daily_press": "https://www.dailypress.senate.gov/",
        "ebb": "https://ebbs.senate.gov/",
        "senate_dems_schedule": "https://www.democrats.senate.gov/floor/senate-schedule",
        "floor_schedule": "https://www.senate.gov/legislative/floor_activity_pail.htm",
        "radio_tv": "https://www.radiotv.senate.gov/",
        "senate_dems_floor": "https://www.democrats.senate.gov/floor",
        "executive_calendar": "https://www.senate.gov/legislative/LIS/executive_calendar/xcalv.pdf",
    }
    if os.getenv("CONGRESS_API_KEY"):
        congress = _env_int("CONGRESS_API_REFRESH_INTERVAL_SECONDS", max(default_interval, 900))
        current_congress = _env_int("CURRENT_CONGRESS", 119)
        sources["congress_committee_meetings"] = f"https://api.congress.gov/v3/committee-meeting/{current_congress}/senate?api_key={os.getenv('CONGRESS_API_KEY')}&format=json"
        intervals = {"congress_committee_meetings": congress}
    else:
        intervals = {}

    configs = []
    for name, url in sources.items():
        env_name = f"SOURCE_{name.upper()}_REFRESH_INTERVAL_SECONDS"
        configs.append(SourceConfig(name=name, url=url, interval_seconds=_env_int(env_name, intervals.get(name, default_interval)), timeout_seconds=timeout))
    return configs


class SourceRefreshManager:
    def __init__(self, sources: Optional[list[SourceConfig]] = None) -> None:
        self.sources = sources or default_source_configs()
        self._task: Optional[asyncio.Task] = None
        self._locks: Dict[str, asyncio.Lock] = {source.name: asyncio.Lock() for source in self.sources}
        self._last_attempt: Dict[str, datetime] = {}
        self._failures: Dict[str, int] = {}
        self._circuit_open_until: Dict[str, datetime] = {}
        self.retries = _env_int("SOURCE_RETRY_ATTEMPTS", 2)
        self.backoff_seconds = _env_float("SOURCE_RETRY_BACKOFF_SECONDS", 1.0)
        self.failure_threshold = _env_int("SOURCE_CIRCUIT_FAILURE_THRESHOLD", 3)
        self.circuit_reset_seconds = _env_int("SOURCE_CIRCUIT_RESET_SECONDS", 900)
        self.disabled = os.getenv("DISABLE_SOURCE_REFRESHER", "").lower() in {"1", "true", "yes"}

    async def start(self) -> None:
        if self.disabled or self._task:
            return
        if os.getenv("SOURCE_REFRESH_ON_STARTUP", "true").lower() in {"1", "true", "yes"}:
            await self.refresh_all(force=True)
        self._task = asyncio.create_task(self._run(), name="senate-source-refresher")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            await self.refresh_due_sources()
            await asyncio.sleep(5)

    async def refresh_due_sources(self) -> None:
        now = datetime.utcnow()
        due = []
        for source in self.sources:
            last = self._last_attempt.get(source.name)
            if last is None or now - last >= timedelta(seconds=source.interval_seconds):
                due.append(source)
        await asyncio.gather(*(self.refresh_source(source) for source in due), return_exceptions=True)

    async def refresh_all(self, force: bool = False) -> None:
        await asyncio.gather(*(self.refresh_source(source, force=force) for source in self.sources), return_exceptions=True)

    async def refresh_source(self, source: SourceConfig, force: bool = False) -> None:
        lock = self._locks[source.name]
        if lock.locked():
            return
        now = datetime.utcnow()
        if not force and self._circuit_open_until.get(source.name, now) > now:
            return
        async with lock:
            self._last_attempt[source.name] = datetime.utcnow()
            try:
                payload = await self._fetch_with_retries(source)
            except Exception as exc:
                failures = self._failures.get(source.name, 0) + 1
                self._failures[source.name] = failures
                if failures >= self.failure_threshold:
                    self._circuit_open_until[source.name] = datetime.utcnow() + timedelta(seconds=self.circuit_reset_seconds)
                upsert_source_failure(source.name, str(exc))
                return
            self._failures[source.name] = 0
            self._circuit_open_until.pop(source.name, None)
            upsert_source_success(source.name, payload)

    async def _fetch_with_retries(self, source: SourceConfig) -> dict:
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                return await self._fetch_once(source)
            except Exception as exc:
                last_exc = exc
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff_seconds * (2 ** attempt))
        raise last_exc or RuntimeError("unknown fetch error")

    async def _fetch_once(self, source: SourceConfig) -> dict:
        httpx = importlib.import_module("httpx")
        timeout = httpx.Timeout(source.timeout_seconds, connect=min(5.0, source.timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(source.url)
            response.raise_for_status()
            return {
                "url": source.url,
                "text": response.text,
                "content_type": response.headers.get("content-type", ""),
                "http_status": response.status_code,
            }

    def status(self) -> dict:
        now = datetime.utcnow()
        return {
            "enabled": not self.disabled,
            "sources": {
                source.name: {
                    "interval_seconds": source.interval_seconds,
                    "last_attempt": self._last_attempt.get(source.name).isoformat() if source.name in self._last_attempt else None,
                    "failures": self._failures.get(source.name, 0),
                    "circuit_open_until": self._circuit_open_until.get(source.name).isoformat() if self._circuit_open_until.get(source.name, now) > now else None,
                }
                for source in self.sources
            },
        }
