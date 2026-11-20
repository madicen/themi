// The wall (WL2, WL3).
// - When a part can't be refreshed, the last good screen stays and says when it was last
//   brought up to date ("Updated 7:40 PM"). The next good refresh clears it.
// - The timeline's blocks are placed from their data- attributes (the site's policy allows
//   no inline styles), and the "now" line moves through the day between refreshes.
(function () {
  "use strict";
  function stale(on) {
    var note = document.getElementById("wall-stale");
    if (!note) return;
    if (on) {
      var stamp = document.querySelector(".wall-stamp");
      note.querySelector("span").textContent = stamp ? stamp.getAttribute("data-at") : "";
    }
    note.hidden = !on;
  }

  function place(root) {
    root.querySelectorAll("[data-x]").forEach(function (el) {
      el.style.left = el.getAttribute("data-x") + "%";
    });
    root.querySelectorAll("[data-w]").forEach(function (el) {
      el.style.width = el.getAttribute("data-w") + "%";
    });
    root.querySelectorAll("[data-lanes]").forEach(function (el) {
      var lanes = Number(el.getAttribute("data-lanes")) || 1;
      var lane = Number(el.getAttribute("data-lane")) || 0;
      if (lanes > 1) {
        el.style.top = (lane * 100) / lanes + "%";
        el.style.height = 100 / lanes + "%";
      }
    });
  }

  function tick() {
    var today = document.querySelector(".wall-today[data-start]");
    if (!today) return;
    var start = Date.parse(today.getAttribute("data-start"));
    var end = Date.parse(today.getAttribute("data-end"));
    var at = Math.min(Math.max((Date.now() - start) / (end - start), 0), 1) * 100;
    var line = today.querySelector(".tl-now");
    if (line) line.style.left = at + "%";
    today.querySelectorAll(".tl-past").forEach(function (el) { el.style.width = at + "%"; });
  }

  // WL5a: a view slides up into #wall-view. Close, a tap on the dimmed screen, or its
  // data-close-after seconds without a touch empty it again.
  var idle = null;
  function closeView() {
    var view = document.getElementById("wall-view");
    if (view) view.innerHTML = "";
    if (idle) { clearTimeout(idle); idle = null; }
  }
  function watchView() {
    if (idle) clearTimeout(idle);
    var sheet = document.querySelector("#wall-view .wall-sheet");
    if (!sheet) { idle = null; return; }
    var seconds = Number(sheet.getAttribute("data-close-after")) || 120;
    idle = setTimeout(closeView, seconds * 1000);
  }
  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest("[data-close]")) closeView();
  });
  document.addEventListener("pointerdown", function () { if (idle) watchView(); });

  document.addEventListener("htmx:sendError", function () { stale(true); });
  document.addEventListener("htmx:responseError", function () { stale(true); });
  document.addEventListener("htmx:afterSwap", function (event) {
    stale(false);
    place(event.target);
    if (event.target.id === "wall-view") watchView();
    if (event.target.id === "wall-night") nightMode();
  });
  // WL6: the night. The night part says whether it's night (data-night); a touch shows
  // the full screen until it's left alone for two minutes.
  var awake = null;
  function nightMode() {
    var mode = document.querySelector("#wall-night .wall-night-mode");
    var night = mode && mode.getAttribute("data-night") === "1";
    document.body.classList.toggle("night", !!night);
    if (!night) wake(false);
  }
  function wake(on) {
    if (awake) { clearTimeout(awake); awake = null; }
    document.body.classList.toggle("awake", on);
    if (on) awake = setTimeout(function () { wake(false); }, 120000);
  }
  document.addEventListener("pointerdown", function () {
    if (document.body.classList.contains("night")) wake(true);
  });

  // WL6: keep the screen on while the wall is open, and ask again when it's seen again.
  function hold() {
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    navigator.wakeLock.request("screen").catch(function () {});
  }
  document.addEventListener("visibilitychange", hold);

  document.addEventListener("DOMContentLoaded", function () {
    place(document);
    nightMode();
    hold();
    setInterval(tick, 60000);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/wall/sw.js", { scope: "/wall" }).catch(function () {});
    }
  });
})();
