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

  document.addEventListener("htmx:sendError", function () { stale(true); });
  document.addEventListener("htmx:responseError", function () { stale(true); });
  document.addEventListener("htmx:afterSwap", function (event) {
    stale(false);
    place(event.target);
  });
  document.addEventListener("DOMContentLoaded", function () {
    place(document);
    setInterval(tick, 60000);
  });
})();
