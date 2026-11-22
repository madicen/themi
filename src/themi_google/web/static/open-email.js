// F56a: try the Gmail app's own link; if the page is still showing after a moment (no
// app, or the phone asked and was told no), show the ways to open it by hand.
(function () {
  "use strict";
  var card = document.getElementById("open-email");
  var more = document.getElementById("open-email-more");
  if (!card || !more) return;
  var app = card.getAttribute("data-app");
  if (!app) return;
  more.hidden = true;
  window.setTimeout(function () { more.hidden = false; }, 1500);
  window.location.href = app;
})();
