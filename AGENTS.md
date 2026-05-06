# AGENTS.md

## Project
The Senate JOLT

FastAPI-based Senate procedural intelligence and operations dashboard.

Primary goal:
Provide reliable real-time Senate procedural information without breaking under load or source instability.

---

## Critical Rules

- DO NOT redesign or modify the UI unless explicitly instructed.
- Preserve all existing frontend behavior.
- Preserve existing route names and response contracts whenever possible.
- Prefer backend-only infrastructure improvements.
- Maintain compatibility with current templates and static assets.
- Do not remove existing features.

---

## Architecture Preferences

- FastAPI application
- SQLite/Postgres acceptable
- Prefer async patterns
- Prefer cached snapshot architecture over live-request scraping
- External Senate sources may fail or change HTML unexpectedly
- Users should receive last-known-good data during outages

---

## Reliability Priorities

1. Background polling instead of request-time scraping
2. Snapshot caching
3. Async HTTP clients
4. Timeouts and retries
5. Circuit breakers for failing sources
6. Graceful degradation
7. Parser test coverage

---

## Security Rules

- Protect debug/admin endpoints
- Never expose secrets or environment variables
- Use ADMIN_TOKEN for protected routes
- Never commit credentials

---

## Coding Style

- Minimal diffs
- High readability
- Avoid unnecessary abstractions
- Add comments only where useful
- Prefer explicit over clever

---

## Testing

Add pytest coverage for:
- parsing logic
- source failures
- stale cache fallback
- event normalization

Tests must not require live internet access.

---

## Important Constraint

This is an operational Senate workflow tool used by politically sophisticated users.

Reliability and procedural continuity are more important than visual redesigns.
