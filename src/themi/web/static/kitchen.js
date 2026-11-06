// RC6: keep the phone's screen on while the kitchen view is open, where the browser offers it.
(function () {
  "use strict";
  var lock = null;
  function hold() {
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    navigator.wakeLock.request("screen").then(function (l) { lock = l; }, function () {});
  }
  document.addEventListener("visibilitychange", hold);
  hold();
})();
