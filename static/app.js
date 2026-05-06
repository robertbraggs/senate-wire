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

  async function refreshLiveData(manual) {
    const y = window.scrollY;
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
      if (nextMain && currentMain) {
        currentMain.innerHTML = nextMain.innerHTML;
        setupEmailSignup();
      }

      const nextAlert = doc.querySelector(".alert-banner");
      const currentAlert = document.querySelector(".alert-banner");
      if (currentAlert && nextAlert) currentAlert.replaceWith(nextAlert);
      if (currentAlert && !nextAlert) currentAlert.remove();
      if (!currentAlert && nextAlert) document.body.prepend(nextAlert);

      const eventsNode = doc.getElementById("notification-events");
      const currentEventsNode = document.getElementById("notification-events");
      if (eventsNode && currentEventsNode) currentEventsNode.textContent = eventsNode.textContent;
      setLastUpdated(new Date());
      setOfflineWarning(false);
      maybeSendNotifications();
      window.scrollTo({ top: y, behavior: manual ? "smooth" : "auto" });
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
    if (!form || !message) return;
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
