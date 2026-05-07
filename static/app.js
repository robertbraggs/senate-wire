(function () {
  const REFRESH_INTERVAL_MS = 60000;
  const DEDUPE_STORAGE_KEY = "senateJoltRecentDedupeKeys";
  const ALERT_PERMISSION_KEY = "senateJoltNotificationPermissionState";
  const MAX_DEDUPE_KEYS = 80;

  function formatTime(date) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  }

  function setLastUpdated(date) {
    const node = document.getElementById("last-updated");
    if (node) node.textContent = `Last updated: ${formatTime(date)}`;
    document.body.dataset.lastUpdated = date.toISOString();
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

  function replaceIfChanged(current, next) {
    if (!current || !next || current.outerHTML === next.outerHTML) return current;
    const active = document.activeElement;
    const minHeight = current.offsetHeight;
    if (minHeight) current.style.minHeight = `${minHeight}px`;
    current.replaceWith(next);
    if (minHeight) {
      next.style.minHeight = `${minHeight}px`;
      window.requestAnimationFrame(() => { next.style.minHeight = ""; });
    }
    if (active && active.id) {
      const restored = document.getElementById(active.id);
      if (restored && typeof restored.focus === "function") restored.focus({ preventScroll: true });
    }
    return next;
  }

  function selectorEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function patchMainContent(nextMain, currentMain) {
    if (!nextMain || !currentMain) return;
    const openState = accordionState(currentMain);
    const nextKeys = new Set();

    nextMain.querySelectorAll("[data-refresh-key]").forEach((nextNode) => {
      const key = nextNode.dataset.refreshKey;
      nextKeys.add(key);
      const currentNode = currentMain.querySelector(`[data-refresh-key="${selectorEscape(key)}"]`);
      if (currentNode) {
        replaceIfChanged(currentNode, nextNode);
      } else {
        currentMain.appendChild(nextNode);
      }
    });

    currentMain.querySelectorAll("[data-refresh-key]").forEach((currentNode) => {
      if (!nextKeys.has(currentNode.dataset.refreshKey)) {
        const placeholder = document.createElement("div");
        placeholder.hidden = true;
        placeholder.dataset.refreshKey = currentNode.dataset.refreshKey;
        currentNode.replaceWith(placeholder);
      }
    });

    restoreAccordionState(currentMain, openState);
  }

  async function refreshLiveData(manual) {
    const y = window.scrollY;
    const x = window.scrollX;
    try {
      const response = await fetch(`${window.location.pathname}?live=1&_=${Date.now()}`, {
        cache: "no-store",
        headers: { "X-Senate-Jolt-Live": "1" }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = await response.text();
      const doc = new DOMParser().parseFromString(text, "text/html");
      const nextMain = doc.getElementById("main-content");
      const currentMain = document.getElementById("main-content");
      patchMainContent(nextMain, currentMain);
      setupEmailSignup();

      const nextAlert = doc.querySelector(".alert-banner");
      const currentAlert = document.querySelector(".alert-banner");
      if (currentAlert && nextAlert) replaceIfChanged(currentAlert, nextAlert);
      if (currentAlert && !nextAlert) currentAlert.remove();
      if (!currentAlert && nextAlert) document.body.prepend(nextAlert);

      const eventsNode = doc.getElementById("notification-events");
      const currentEventsNode = document.getElementById("notification-events");
      if (eventsNode && currentEventsNode && currentEventsNode.textContent !== eventsNode.textContent) currentEventsNode.textContent = eventsNode.textContent;
      setLastUpdated(new Date());
      setOfflineWarning(false);
      maybeSendNotifications();
      window.requestAnimationFrame(() => {
        window.scrollTo({ left: x, top: y, behavior: "auto" });
        window.requestAnimationFrame(() => window.scrollTo({ left: x, top: y, behavior: "auto" }));
      });
    } catch (error) {
      setOfflineWarning(true);
      if (manual) console.warn("Senate JOLT live refresh failed", error);
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
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/static/service-worker.js").catch((error) => {
        console.warn("Senate JOLT service worker registration failed", error);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupServiceWorker();
    setupNotifications();
    setupEmailSignup();
    setLastUpdated(new Date(document.body.dataset.lastUpdated || Date.now()));
    const refresh = document.getElementById("refresh-button");
    if (refresh) refresh.addEventListener("click", () => refreshLiveData(true));
    window.setInterval(() => refreshLiveData(false), REFRESH_INTERVAL_MS);
  });
})();
