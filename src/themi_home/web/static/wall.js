// The wall (WL2): when a part can't be refreshed, the last good screen stays and says when
// it was last brought up to date ("Updated 7:40 PM"). The next good refresh clears it.
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
  document.addEventListener("htmx:sendError", function () { stale(true); });
  document.addEventListener("htmx:responseError", function () { stale(true); });
  document.addEventListener("htmx:afterSwap", function () { stale(false); });
})();
