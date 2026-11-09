// CK1: the cook screen. The server is the truth: every 5 seconds the page asks
// /session/state, and when what it shows has changed ("drawn"), it fetches its regions again
// from /session/cook/view. Timers count down in between from the server's ends_at.
// The plumbing (the session header, reload with a ticket, the error report, the wake lock)
// is the body double page's (session.js), kept the same.
(function () {
  "use strict";
  var body = document.body;
  var POLL = 5000;
  var session = body.dataset.session || "";
  if (location.search.indexOf("ticket=") !== -1) history.replaceState(null, "", "/session" + location.hash);
  var offset = body.dataset.now ? Date.parse(body.dataset.now) - Date.now() : 0;

  var reported = 0;
  function report(what) {
    if (reported++ > 20) return;
    try {
      fetch("/session/report", { method: "POST", credentials: "same-origin", body: String(what).slice(0, 500),
        headers: auth({ "Content-Type": "text/plain" }) }).then(function () {}, function () {});
    } catch (e) { /* nothing more to do */ }
  }
  window.addEventListener("error", function (e) {
    report("cook error: " + e.message + " at " + (e.filename || "").split("/").pop() + ":" + e.lineno);
  });

  function auth(headers) {
    headers = headers || {};
    if (session) headers["X-Themi-Session"] = session;
    return headers;
  }

  function reload() {
    if (!session) { location.reload(); return; }
    fetch("/session/ticket", {
      method: "POST", credentials: "same-origin",
      headers: auth({ "X-CSRF-Token": body.dataset.csrf })
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (t) {
        if (t && t.ticket) location.replace("/session?ticket=" + encodeURIComponent(t.ticket) + location.hash);
        else location.reload();
      }, function () { location.reload(); });
  }

  function main() { return document.querySelector(".cook-main"); }

  function two(n) { return (n < 10 ? "0" : "") + n; }
  function words(ms) {
    var s = Math.max(0, Math.ceil(ms / 1000));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? h + ":" + two(m) + ":" + two(s % 60) : m + ":" + two(s % 60);
  }

  function tick() {
    var now = Date.now() + offset;
    var cards = document.querySelectorAll(".cook-timer[data-ends]");
    for (var i = 0; i < cards.length; i++) {
      var left = cards[i].querySelector(".cook-timer-left");
      if (!left || cards[i].dataset.fired) continue;
      left.textContent = words(Date.parse(cards[i].dataset.ends) - now);
    }
    if (window.themiCook && window.themiCook.onTick) window.themiCook.onTick(now);
  }

  function view() {
    return fetch("/session/cook/view", { credentials: "same-origin", cache: "no-store", headers: auth() })
      .then(function (r) {
        if (r.status === 204) { reload(); return null; }
        return r.ok ? r.text() : null;
      })
      .then(function (html) {
        if (html === null || html === undefined) return;
        var box = document.getElementById("cook");
        box.innerHTML = html;
        tick();
        if (window.themiCook && window.themiCook.onDraw) window.themiCook.onDraw();
      }, function (e) { report("view failed: " + e); });
  }

  function redraw(state) {
    if (!state || !state.active || state.kind !== "cooking") { reload(); return; }
    offset = Date.parse(state.now) - Date.now();
    var shown = main();
    if (!shown || String(state.id) !== shown.dataset.session) { reload(); return; }
    if (state.drawn !== shown.dataset.drawn) view();
    if (window.themiCook && window.themiCook.onState) window.themiCook.onState(state);
  }

  function poll() {
    fetch("/session/state", { credentials: "same-origin", cache: "no-store", headers: auth() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) redraw(s); }, function () {});
  }

  // Every tap is a form posted with fetch (with the session header), then the state redrawn.
  // Each form has a hidden input named "action", which shadows form.action: read the attribute.
  function post(form, extra) {
    var data = new URLSearchParams(new FormData(form));
    if (extra) Object.keys(extra).forEach(function (k) { data.set(k, extra[k]); });
    return fetch(form.getAttribute("action"), {
      method: "POST", body: data.toString(), credentials: "same-origin",
      headers: auth({ "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" })
    }).then(function (r) {
      if (!r.ok) report("cook tap " + data.get("action") + " answered " + r.status);
      return r.ok ? r.json() : null;
    }).then(function (s) { if (s) redraw(s); return s; }, function (e) { report("cook tap failed: " + e); });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.closest || !form.closest("#cook")) return;
    if (form.dataset.local) return;  // a form the page handles itself
    event.preventDefault();
    post(form);
  });

  // Swipe left for Next (or All done), right for Back.
  var startX = null, startY = null;
  document.addEventListener("touchstart", function (e) {
    if (e.touches.length !== 1) { startX = null; return; }
    startX = e.touches[0].clientX; startY = e.touches[0].clientY;
  }, { passive: true });
  document.addEventListener("touchend", function (e) {
    if (startX === null) return;
    var dx = e.changedTouches[0].clientX - startX, dy = e.changedTouches[0].clientY - startY;
    startX = null;
    if (Math.abs(dx) < 60 || Math.abs(dy) > 50) return;
    if (document.querySelector(".cook-drawer:not([hidden])")) return;
    var form = dx < 0
      ? document.querySelector('form[data-move="next"], form[data-move="finish"]')
      : document.querySelector('form[data-move="back"]');
    if (form) post(form);
  }, { passive: true });

  var lock = null;
  function hold() { // keep the screen on, where the browser offers it
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    navigator.wakeLock.request("screen").then(function (l) { lock = l; }, function () {});
  }

  window.themiCook = window.themiCook || {};
  window.themiCook.post = post;
  window.themiCook.poll = poll;
  window.themiCook.view = view;
  window.themiCook.auth = auth;
  window.themiCook.report = report;
  window.themiCook.now = function () { return Date.now() + offset; };

  document.addEventListener("visibilitychange", function () { hold(); if (document.visibilityState === "visible") poll(); });
  hold();
  tick();
  setInterval(tick, 1000);
  setInterval(poll, POLL);
})();
