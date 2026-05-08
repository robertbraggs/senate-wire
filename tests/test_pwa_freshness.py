from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_homepage_exposes_client_refreshable_current_date_hook():
    main_source = read_text("app/main.py")

    assert 'id="current-date"' in main_source
    assert 'data-server-rendered-date' in main_source
    assert '<script src="/static/app.js?v=20260508"></script>' in main_source
    assert '"Cache-Control": "no-store, max-age=0, must-revalidate"' in main_source
    assert '"Cache-Control": "no-cache, max-age=0, must-revalidate"' in main_source


def test_client_date_time_refreshes_on_load_poll_and_pwa_resume():
    app_js = read_text("static/app.js")

    assert 'function refreshCurrentDateTime(date)' in app_js
    assert 'dateNode.textContent = formatDate(current)' in app_js
    assert 'refreshCurrentDateTime(refreshedAt)' in app_js
    assert 'setLastUpdated(new Date())' in app_js
    assert 'window.setInterval(() => refreshCurrentDateTime(new Date()), CURRENT_TIME_REFRESH_MS)' in app_js
    assert 'window.addEventListener("pageshow", refreshAfterResume)' in app_js
    assert 'window.addEventListener("focus", refreshAfterResume)' in app_js
    assert 'document.addEventListener("visibilitychange"' in app_js
    assert 'cache: "no-store"' in app_js
    assert 'navigator.serviceWorker.register("/service-worker.js")' in app_js


def test_service_workers_do_not_cache_date_bearing_homepage_shell():
    root_sw = read_text("service-worker.js")
    static_sw = read_text("static/service-worker.js")

    assert 'PRECACHE_URLS = ["/"' not in root_sw
    assert 'url.pathname === "/"' in root_sw
    assert 'cache: "no-store"' in root_sw
    assert 'caches.match("/")' not in root_sw
    assert 'cacheName.startsWith("senate-jolt")' in root_sw

    assert 'senate-jolt-shell-v3' in static_sw
    assert 'url.searchParams.has("live")' in static_sw
    assert 'cache: "no-store"' in static_sw
    assert 'date-bearing HTML' in static_sw
