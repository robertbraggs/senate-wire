from pathlib import Path

from fastapi.testclient import TestClient

from app import main

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_homepage_exposes_client_refreshable_current_date_hook():
    main_source = read_text("app/main.py")

    assert 'id="current-date"' in main_source
    assert 'data-server-rendered-date' in main_source
    assert '<script src="/static/app.js?v=20260508b"></script>' in main_source
    assert 'def no_store_headers()' in main_source
    assert '"Cache-Control": "no-store, max-age=0, must-revalidate"' in main_source
    assert '"Cache-Control": "no-cache, max-age=0, must-revalidate"' in main_source


def test_client_date_time_refreshes_on_boot_load_poll_and_pwa_resume():
    app_js = read_text("static/app.js")

    assert 'function refreshCurrentDateTime(date)' in app_js
    assert 'function refreshCurrentDisplays(date)' in app_js
    assert 'dateNode.textContent = formatDate(current)' in app_js
    assert 'refreshCurrentDateTime(refreshedAt)' in app_js
    assert 'boot();' in app_js
    assert 'document.addEventListener("DOMContentLoaded", boot)' in app_js
    assert 'window.addEventListener("load", () => refreshCurrentDisplays(new Date()))' in app_js
    assert 'window.setInterval(() => refreshCurrentDisplays(new Date()), CURRENT_TIME_REFRESH_MS)' in app_js
    assert 'window.addEventListener("pageshow", refreshAfterResume)' in app_js
    assert 'event.persisted' in app_js
    assert 'window.addEventListener("focus", refreshAfterResume)' in app_js
    assert 'document.addEventListener("visibilitychange"' in app_js
    assert 'cache: "no-store"' in app_js
    assert 'navigator.serviceWorker.register("/service-worker.js")' in app_js


def test_date_render_function_is_idempotent_by_replacing_text_only():
    app_js = read_text("static/app.js")
    function_body = app_js.split('function refreshCurrentDateTime(date)', 1)[1].split('function setLastUpdated', 1)[0]

    assert 'dateNode.textContent = formatDate(current)' in function_body
    assert 'appendChild' not in function_body
    assert 'insertAdjacentHTML' not in function_body
    assert 'innerHTML' not in function_body


def test_service_workers_do_not_cache_date_bearing_homepage_shell():
    root_sw = read_text("service-worker.js")
    static_sw = read_text("static/service-worker.js")

    assert 'PRECACHE_URLS = ["/"' not in root_sw
    assert 'url.pathname === "/"' in root_sw
    assert 'url.pathname === "/events"' in root_sw
    assert 'url.pathname === "/summary"' in root_sw
    assert 'cache: "no-store"' in root_sw
    assert 'caches.match("/")' not in root_sw
    assert 'cacheName.startsWith("senate-jolt")' in root_sw

    assert 'senate-jolt-shell-v4' in static_sw
    assert 'url.searchParams.has("live")' in static_sw
    assert 'url.pathname === "/events"' in static_sw
    assert 'url.pathname === "/summary"' in static_sw
    assert 'cache: "no-store"' in static_sw
    assert 'date-bearing HTML' in static_sw


def test_dynamic_status_routes_send_no_store_headers(monkeypatch):
    monkeypatch.setattr(main, "get_all_items", lambda: [])
    client = TestClient(main.app)

    for path in ("/events", "/summary", "/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, max-age=0, must-revalidate"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["expires"] == "0"


def test_mobile_pwa_date_element_is_not_hidden_in_standalone_mode():
    main_source = read_text("app/main.py")

    assert '@media (display-mode: standalone)' in main_source
    assert '.sub:first-of-type {{ display: none; }}' not in main_source
    assert '#current-date {{ display: inline; }}' in main_source
