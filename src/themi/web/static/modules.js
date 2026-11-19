// MP6: the Modules page, quicker to use. Everything here is an extra: without it the
// search is a form, the groups are <details>, and the page works the same.
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var KEY = "themi.modules.folded";

  function folded() {
    try {
      return JSON.parse(window.localStorage.getItem(KEY) || "{}") || {};
    } catch (e) {
      return {};
    }
  }

  function remember(id, open) {
    try {
      var all = folded();
      all[id] = !open;
      window.localStorage.setItem(KEY, JSON.stringify(all));
    } catch (e) {
      /* no storage here: groups just open as the page says */
    }
  }

  function words(el) {
    return (el.textContent || "").toLowerCase();
  }

  function filter(text) {
    var q = text.trim().toLowerCase();
    var groups = document.querySelectorAll(".module-group");
    groups.forEach(function (group) {
      var title = words(group.querySelector("summary h2"));
      var all = q && title.indexOf(q) !== -1;
      var any = false;
      group.querySelectorAll(".module-list > li").forEach(function (card) {
        var hit = !q || all || words(card).indexOf(q) !== -1;
        card.hidden = !hit;
        any = any || hit;
      });
      group.hidden = !any;
      if (q && any) group.open = true;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var params = new URLSearchParams(window.location.search);
    var searching = params.get("q") || (params.get("show") && params.get("show") !== "all");
    var saved = folded();
    document.querySelectorAll(".module-group").forEach(function (group) {
      if (!searching && Object.prototype.hasOwnProperty.call(saved, group.id)) {
        group.open = !saved[group.id];
      }
      group.addEventListener("toggle", function () {
        if (!document.getElementById("module-find").value) remember(group.id, group.open);
      });
    });
    var find = document.getElementById("module-find");
    if (!find) return;
    find.addEventListener("input", function () {
      filter(find.value);
    });
    document.getElementById("module-search").addEventListener("submit", function (event) {
      event.preventDefault();
      filter(find.value);
    });
    document.addEventListener("keydown", function (event) {
      var tag = (event.target.tagName || "").toLowerCase();
      if (event.key === "/" && tag !== "input" && tag !== "textarea" && tag !== "select") {
        event.preventDefault();
        find.focus();
      }
    });
  });
})();
