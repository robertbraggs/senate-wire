(function () {
  const REFRESH_INTERVAL_MS = 60000;
  const CURRENT_TIME_REFRESH_MS = 30000;
  const DEDUPE_STORAGE_KEY = "senateJoltRecentDedupeKeys";
  const ALERT_PERMISSION_KEY = "senateJoltNotificationPermissionState";
  const MAX_DEDUPE_KEYS = 80;
  const SCROLL_IDLE_MS = 700;

  function debugRefreshEnabled() {
    if (new URLSearchParams(window.location.search).has("debug_refresh")) return true;
    try { return localStorage.getItem("senateJoltDebugRefresh") === "true"; }
    catch (_) { return false; }
  }

  const DEBUG_REFRESH = debugRefreshEnabled();
  let scrollVersion = 0;
  let scrolling = false;
  let scrollIdleTimer = null;
  let refreshInFlight = false;
  let pendingRefresh = false;
  let pendingRefreshText = null;

  function debugLog(message, detail) {
    if (!DEBUG_REFRESH) return;
    console.debug(`[Senate JOLT refresh] ${message}`, detail || "");
  }

  function captureRefreshState(root) {
    return {
      x: window.scrollX,
      y: window.scrollY,
      scrollVersion,
      activeElementId: document.activeElement && document.activeElement.id ? document.activeElement.id : "",
      accordions: root ? accordionState(root) : {}
    };
  }

  function restoreScrollIfStable(state) {
    if (!state || scrollVersion !== state.scrollVersion) {
      debugLog("scroll restore skipped", { before: state && state.y, after: window.scrollY, scrollVersion });
      return;
    }
    window.requestAnimationFrame(() => {
      window.scrollTo({ left: state.x, top: state.y, behavior: "auto" });
      window.requestAnimationFrame(() => {
        window.scrollTo({ left: state.x, top: state.y, behavior: "auto" });
        debugLog("scroll restored", { before: state.y, after: window.scrollY });
      });
    });
  }

  function markScrolling() {
    scrolling = true;
    scrollVersion += 1;
    if (scrollIdleTimer) window.clearTimeout(scrollIdleTimer);
    scrollIdleTimer = window.setTimeout(() => {
      scrolling = false;
      if (pendingRefresh || pendingRefreshText) {
        debugLog("deferred refresh released", { scrollY: window.scrollY });
        if (pendingRefreshText) {
          const text = pendingRefreshText;
          pendingRefreshText = null;
          pendingRefresh = false;
          applyRefreshText(text, false);
        } else {
          pendingRefresh = false;
          refreshLiveData(false);
        }
      }
    }, SCROLL_IDLE_MS);
  }


  function formatTime(date) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  }

  function formatDate(date) {
    return date.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  }

  function refreshCurrentDateTime(date) {
    const current = date || new Date();
    const dateNode = document.getElementById("current-date");
    if (dateNode) dateNode.textContent = formatDate(current);
    if (document.body) document.body.dataset.currentDate = current.toISOString();
  }

  function setLastUpdated(date) {
    const current = date || new Date();
    const node = document.getElementById("last-updated");
    if (node) node.textContent = `Last updated: ${formatTime(current)}`;
    if (document.body) document.body.dataset.lastUpdated = current.toISOString();
  }

  function refreshCurrentDisplays(date) {
    const current = date || new Date();
    refreshCurrentDateTime(current);
    setLastUpdated(current);
  }

  function setOfflineWarning(show) {
    const warning = document.getElementById("offline-warning");
    if (warning) warning.hidden = !show;
  }

  function accordionState(root) {
    const state = {};
    root.querySelectorAll("details[data-accordion-key]").forEach((node) => {
      state[node.dataset.accordionKey] = node.open;
    });
    return state;
  }

  function restoreAccordionState(root, state) {
    root.querySelectorAll("details[data-accordion-key]").forEach((node) => {
      if (Object.prototype.hasOwnProperty.call(state, node.dataset.accordionKey)) {
        node.open = state[node.dataset.accordionKey];
      }
    });
  }

  function withReservedHeight(node, update) {
    const minHeight = node.offsetHeight;
    if (minHeight) node.style.minHeight = `${minHeight}px`;
    update();
    if (minHeight) {
      window.requestAnimationFrame(() => { node.style.minHeight = ""; });
    }
  }

  function patchAttributes(current, next) {
    Array.from(current.attributes).forEach((attribute) => {
      if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
    });
    Array.from(next.attributes).forEach((attribute) => {
      if (current.getAttribute(attribute.name) !== attribute.value) {
        current.setAttribute(attribute.name, attribute.value);
      }
    });
  }

  function patchDetailsInPlace(currentDetails, nextDetails) {
    const wasOpen = currentDetails.open;
    patchAttributes(currentDetails, nextDetails);
    currentDetails.open = wasOpen;

    const currentSummary = currentDetails.querySelector(":scope > summary");
    const nextSummary = nextDetails.querySelector(":scope > summary");
    if (currentSummary && nextSummary && currentSummary.innerHTML !== nextSummary.innerHTML) {
      currentSummary.innerHTML = nextSummary.innerHTML;
    }

    const nextBody = Array.from(nextDetails.childNodes).filter((node) => node.nodeName.toLowerCase() !== "summary");
    Array.from(currentDetails.childNodes).forEach((node) => {
      if (node.nodeName.toLowerCase() !== "summary") node.remove();
    });
    nextBody.forEach((node) => currentDetails.appendChild(node));
    currentDetails.open = wasOpen;
  }

  function patchElementInPlace(current, next) {
    if (!current || !next || current.outerHTML === next.outerHTML) return current;

    if (current.tagName === next.tagName) {
      withReservedHeight(current, () => {
        patchAttributes(current, next);
        const currentDetails = current.matches("details[data-accordion-key]") ? current : current.querySelector(":scope details[data-accordion-key]");
        const nextDetails = next.matches("details[data-accordion-key]") ? next : next.querySelector(":scope details[data-accordion-key]");
        if (currentDetails && nextDetails) {
          patchDetailsInPlace(currentDetails, nextDetails);
        } else {
          current.innerHTML = next.innerHTML;
        }
      });
      return current;
    }

    const minHeight = current.offsetHeight;
    if (minHeight) next.style.minHeight = `${minHeight}px`;
    current.replaceWith(next);
    if (minHeight) window.requestAnimationFrame(() => { next.style.minHeight = ""; });
    return next;
  }

  function replaceIfChanged(current, next) {
    return patchElementInPlace(current, next);
  }

  function selectorEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function patchMainContent(nextMain, currentMain, preservedState) {
    if (!nextMain || !currentMain) return;
    const openState = preservedState && preservedState.accordions ? preservedState.accordions : accordionState(currentMain);
    const nextKeys = new Set();

    nextMain.querySelectorAll("[data-refresh-key]").forEach((nextNode) => {
      const key = nextNode.dataset.refreshKey;
      nextKeys.add(key);
      const currentNode = currentMain.querySelector(`[data-refresh-key="${selectorEscape(key)}"]`);
      if (currentNode) {
        patchElementInPlace(currentNode, nextNode);
      } else {
        currentMain.appendChild(nextNode);
      }
    });

    currentMain.querySelectorAll("[data-refresh-key]").forEach((currentNode) => {
      if (!nextKeys.has(currentNode.dataset.refreshKey)) {
        const placeholder = document.createElement("div");
        const minHeight = currentNode.offsetHeight;
        placeholder.setAttribute("aria-hidden", "true");
        placeholder.dataset.refreshKey = currentNode.dataset.refreshKey;
        placeholder.dataset.stabilizePlaceholder = "true";
        if (minHeight) placeholder.style.minHeight = `${minHeight}px`;
        currentNode.replaceWith(placeholder);
        if (minHeight) window.requestAnimationFrame(() => { placeholder.style.minHeight = "0px"; });
      }
    });

    restoreAccordionState(currentMain, openState);
  }

  function applyRefreshText(text, manual) {
    const currentMain = document.getElementById("main-content");
    const state = captureRefreshState(currentMain);
    if (!manual && scrolling) {
      pendingRefreshText = text;
      debugLog("refresh apply deferred due to scrolling", { scrollY: state.y });
      return;
    }
    try {
      const doc = new DOMParser().parseFromString(text, "text/html");
      const nextMain = doc.getElementById("main-content");
      debugLog("refresh applying", { scrollY: state.y, activeElementId: state.activeElementId });
      patchMainContent(nextMain, currentMain, state);
      setupEmailSignup();

      const nextAlert = doc.querySelector(".alert-banner");
      const currentAlert = document.querySelector(".alert-banner");
      if (currentAlert && nextAlert) patchElementInPlace(currentAlert, nextAlert);
      if (currentAlert && !nextAlert) currentAlert.remove();
      if (!currentAlert && nextAlert) document.body.prepend(nextAlert);

      const eventsNode = doc.getElementById("notification-events");
      const currentEventsNode = document.getElementById("notification-events");
      if (eventsNode && currentEventsNode && currentEventsNode.textContent !== eventsNode.textContent) currentEventsNode.textContent = eventsNode.textContent;
      const refreshedAt = new Date();
      refreshCurrentDateTime(refreshedAt);
      setLastUpdated(refreshedAt);
      setOfflineWarning(false);
      maybeSendNotifications();
      restoreScrollIfStable(state);
      debugLog("refresh applied", { before: state.y, after: window.scrollY });
    } catch (error) {
      setOfflineWarning(true);
      if (manual) console.warn("Senate JOLT live refresh failed", error);
    }
  }

  async function refreshLiveData(manual) {
    if (!manual && scrolling) {
      pendingRefresh = true;
      debugLog("refresh fetch deferred due to scrolling", { scrollY: window.scrollY });
      return;
    }
    if (refreshInFlight) {
      if (!manual) pendingRefresh = true;
      return;
    }
    refreshInFlight = true;
    const state = captureRefreshState(document.getElementById("main-content"));
    debugLog("refresh started", { manual: !!manual, scrollY: state.y });
    try {
      const response = await fetch(`${window.location.pathname}?live=1&_=${Date.now()}`, {
        cache: "no-store",
        headers: { "X-Senate-Jolt-Live": "1" }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = await response.text();
      applyRefreshText(text, manual);
    } catch (error) {
      setOfflineWarning(true);
      if (manual) console.warn("Senate JOLT live refresh failed", error);
    } finally {
      refreshInFlight = false;
    }
  }

  function getRecentKeys() {
    try { return JSON.parse(localStorage.getItem(DEDUPE_STORAGE_KEY) || "[]"); }
    catch (_) { return []; }
  }

  function storeRecentKeys(keys) {
    localStorage.setItem(DEDUPE_STORAGE_KEY, JSON.stringify(keys.slice(-MAX_DEDUPE_KEYS)));
  }

  function getNotificationEvents() {
    const node = document.getElementById("notification-events");
    if (!node || !node.textContent.trim()) return [];
    try { return JSON.parse(node.textContent); }
    catch (_) { return []; }
  }

  function maybeSendNotifications() {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const recent = getRecentKeys();
    const recentSet = new Set(recent);
    const sendable = new Set(["vote_underway", "vote_block_within_60", "ebb_media_event", "cloture_filed", "major_schedule_change"]);
    getNotificationEvents().forEach((event) => {
      if (!sendable.has(event.coverage_type) || recentSet.has(event.dedupe_key)) return;
      new Notification(event.title, { body: event.body, tag: event.dedupe_key, data: event });
      recent.push(event.dedupe_key);
      recentSet.add(event.dedupe_key);
    });
    storeRecentKeys(recent);
  }

  function setupNotifications() {
    const button = document.getElementById("enable-alerts");
    if (!button || !("Notification" in window)) return;
    button.hidden = false;
    localStorage.setItem(ALERT_PERMISSION_KEY, Notification.permission);
    if (Notification.permission === "granted") {
      button.textContent = "Alerts enabled";
      maybeSendNotifications();
    } else if (Notification.permission === "denied") {
      button.textContent = "Alerts blocked";
      button.disabled = true;
    }
    button.addEventListener("click", async () => {
      if (Notification.permission === "granted") {
        maybeSendNotifications();
        return;
      }
      const permission = await Notification.requestPermission();
      localStorage.setItem(ALERT_PERMISSION_KEY, permission);
      if (permission === "granted") {
        button.textContent = "Alerts enabled";
        maybeSendNotifications();
      } else if (permission === "denied") {
        button.textContent = "Alerts blocked";
        button.disabled = true;
      }
    });
  }


  function setupEmailSignup() {
    const form = document.getElementById("alerts-signup-form");
    const message = document.getElementById("alerts-signup-message");
    if (!form || !message || form.dataset.bound === "true") return;
    form.dataset.bound = "true";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      message.textContent = "";
      message.className = "signup-message";
      const email = (form.email && form.email.value || "").trim();
      if (!email || !form.email.checkValidity()) {
        message.textContent = "Please enter a valid email address.";
        message.classList.add("error");
        return;
      }
      try {
        const response = await fetch(form.action, {
          method: "POST",
          headers: { "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
          body: new URLSearchParams(new FormData(form))
        });
        const data = await response.json();
        message.textContent = data.message || (response.ok ? "You’re signed up for Senate JOLT alerts." : "Please enter a valid email address.");
        message.classList.add(response.ok && data.ok !== false ? "success" : "error");
        if (response.ok && data.ok !== false) form.reset();
      } catch (_) {
        message.textContent = "Please enter a valid email address.";
        message.classList.add("error");
      }
    });
  }

  function setupServiceWorker() {
    if (!("serviceWorker" in navigator) || setupServiceWorker.bound) return;
    setupServiceWorker.bound = true;
    const register = () => {
      navigator.serviceWorker.register("/service-worker.js").catch((error) => {
        console.warn("Senate JOLT service worker registration failed", error);
      });
    };
    if (document.readyState === "complete") {
      register();
    } else {
      window.addEventListener("load", register, { once: true });
    }
  }

  function refreshAfterResume(event) {
    refreshCurrentDisplays(new Date());
    if (!event || event.persisted || document.visibilityState !== "hidden") {
      refreshLiveData(false);
    }
  }

  function setupLayoutShiftLogging() {
    if (!DEBUG_REFRESH || !("PerformanceObserver" in window) || setupLayoutShiftLogging.bound) return;
    setupLayoutShiftLogging.bound = true;
    try {
      const observer = new PerformanceObserver((list) => {
        list.getEntries().forEach((entry) => {
          if (!entry.hadRecentInput) debugLog("layout shift", { value: entry.value, scrollY: window.scrollY });
        });
      });
      observer.observe({ type: "layout-shift", buffered: true });
    } catch (_) {}
  }

  function boot() {
    refreshCurrentDisplays(new Date());
    setupServiceWorker();
    setupNotifications();
    setupEmailSignup();
    setupLayoutShiftLogging();
    const refresh = document.getElementById("refresh-button");
    if (refresh && refresh.dataset.bound !== "true") {
      refresh.dataset.bound = "true";
      refresh.addEventListener("click", () => refreshLiveData(true));
    }
  }

  window.addEventListener("scroll", markScrolling, { passive: true });
  boot();
  document.addEventListener("DOMContentLoaded", boot);
  window.addEventListener("load", () => refreshCurrentDisplays(new Date()));
  window.setInterval(() => refreshLiveData(false), REFRESH_INTERVAL_MS);
  window.setInterval(() => refreshCurrentDisplays(new Date()), CURRENT_TIME_REFRESH_MS);
  window.addEventListener("pageshow", refreshAfterResume);
  window.addEventListener("focus", refreshAfterResume);
  document.addEventListener("visibilitychange", () => {
    refreshCurrentDisplays(new Date());
    if (!document.hidden) refreshAfterResume();
  });
})();
