// Account-local auction countdowns. Display/notify only: never fetches a source
// site, signs in, or places a bid.
(() => {
  "use strict";

  const rows = [...document.querySelectorAll(".bid-row[data-end]")];
  if (!rows.length) return;

  const milestones = [60, 120, 300, 900, 1800, 2700, 3600, 7200];
  const channel = "BroadcastChannel" in window ? new BroadcastChannel("dealsniffer-bid-alerts") : null;
  const nav = document.getElementById("my-bids-nav");

  function compact(seconds) {
    if (seconds <= 0) return "closing now — refresh the original listing";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function label(seconds) {
    if (seconds === 7200) return "2 hours";
    if (seconds === 3600) return "1 hour";
    return `${Math.floor(seconds / 60)} minutes`;
  }

  function seenKey(row, seconds) {
    return `dealsniffer.bid-alert.v1:${row.dataset.bid}:${row.dataset.end}:${seconds}`;
  }

  function claim(row, seconds) {
    const key = seenKey(row, seconds);
    try {
      if (localStorage.getItem(key)) return false;
      localStorage.setItem(key, new Date().toISOString());
    } catch (_) {
      // The on-page warning remains useful when storage is unavailable.
    }
    if (channel) channel.postMessage({key});
    return true;
  }

  function warn(row, seconds) {
    const title = row.querySelector(".bid-title b")?.textContent?.trim() || "Watched auction";
    const message = `${title}: ${label(seconds)} until the scheduled close. Refresh the original listing; HiBid soft-close may extend it.`;
    row.classList.add("bid-urgent");
    const alert = row.querySelector(".bid-alert");
    if (alert) alert.textContent = message;
    if (nav) {
      nav.classList.add("bid-nav-urgent");
      nav.dataset.bidUrgent = "1";
    }
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("DealSniffer bid alert", {body: message, tag: seenKey(row, seconds), renotify: true});
    }
  }

  function tick() {
    const now = Date.now();
    let urgent = false;
    for (const row of rows) {
      if (!row.dataset.end || ["won", "lost", "closed"].includes(row.dataset.status)) continue;
      const end = Date.parse(row.dataset.end);
      if (!Number.isFinite(end)) continue;
      const left = Math.max(0, Math.ceil((end - now) / 1000));
      const counter = row.querySelector(".bid-countdown");
      if (counter) counter.textContent = `closes in ${compact(left)}`;
      if (left <= 900) {
        urgent = true;
        row.classList.add("bid-urgent");
      }
      const prior = Number(row.dataset.previousSeconds || left + 1);
      const crossed = milestones.filter(t => prior > t && left <= t).pop();
      const initial = !row.dataset.previousSeconds ? milestones.find(t => left <= t) : null;
      const milestone = crossed || initial;
      if (milestone && claim(row, milestone)) warn(row, milestone);
      row.dataset.previousSeconds = String(left);
    }
    if (nav && urgent) nav.classList.add("bid-nav-urgent");
  }

  const enable = document.createElement("button");
  enable.type = "button";
  enable.className = "mk-view";
  enable.textContent = "Enable browser bid alerts";
  enable.hidden = !("Notification" in window) || Notification.permission === "granted";
  enable.addEventListener("click", async () => {
    const permission = await Notification.requestPermission();
    enable.hidden = permission === "granted";
    enable.textContent = permission === "denied" ? "Browser alerts blocked" : "Enable browser bid alerts";
  });
  const heading = document.querySelector(".bid-head");
  if (heading) heading.append(enable);

  window.addEventListener("storage", event => {
    if (event.key?.startsWith("dealsniffer.bid-alert.v1:")) tick();
  });
  if (channel) channel.onmessage = () => tick();
  tick();
  setInterval(tick, 1000);
})();
