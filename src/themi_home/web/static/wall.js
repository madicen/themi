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

  // F59g (idea #257): the Talk sheet's mic, only where the frame can record. A tap starts,
  // a second (or 30 s) stops and sends the clip; the answer replaces the sheet.
  var recorder = null;
  function canRecord() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }
  function showMics(root) {
    if (!canRecord()) return;
    root.querySelectorAll("[data-talk-mic]").forEach(function (b) { b.hidden = false; });
  }
  function sendClip(button, blob) {
    var form = new FormData();
    form.append("member", button.getAttribute("data-member"));
    form.append("audio", blob, "clip.webm");
    var token = (JSON.parse(document.body.getAttribute("hx-headers") || "{}"))["X-CSRF-Token"] || "";
    fetch("/wall/say", { method: "POST", body: form, headers: { "X-CSRF-Token": token, "HX-Request": "true" } })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var view = document.getElementById("wall-view");
        if (!view) return;
        view.innerHTML = html;
        if (window.htmx) window.htmx.process(view);
        showMics(view);
      });
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-talk-mic]");
    if (!button) return;
    event.preventDefault();
    if (recorder) { recorder.stop(); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        button.classList.remove("on");
        var type = recorder.mimeType || "audio/webm";
        recorder = null;
        if (chunks.length) sendClip(button, new Blob(chunks, { type: type }));
      };
      recorder.start();
      button.classList.add("on");
      setTimeout(function () { if (recorder) recorder.stop(); }, 30000);
    }).catch(function () { button.hidden = true; });
  });
  document.addEventListener("htmx:afterSwap", function (event) { showMics(event.target); });

  // F59f (idea #258): on the calendar screen, a swipe left or right is › or ‹.
  var swipeFrom = null;
  document.addEventListener("touchstart", function (event) {
    var area = event.target.closest && event.target.closest("[data-swipe]");
    swipeFrom = area && event.touches.length === 1
      ? { x: event.touches[0].clientX, y: event.touches[0].clientY } : null;
  }, { passive: true });
  document.addEventListener("touchend", function (event) {
    if (!swipeFrom || !event.changedTouches.length) return;
    var dx = event.changedTouches[0].clientX - swipeFrom.x;
    var dy = event.changedTouches[0].clientY - swipeFrom.y;
    swipeFrom = null;
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    var go = document.querySelector(dx < 0 ? "[data-swipe-next]" : "[data-swipe-prev]");
    if (go) go.click();
  });

  document.addEventListener("htmx:sendError", function () { stale(true); });
  document.addEventListener("htmx:responseError", function () { stale(true); });
  // F58c: the columns give up what doesn't fit on the frame ("+N more", wall-fit.js).
  function fit() { if (window.themiWallFit) window.themiWallFit.fitWall(document); }
  var refit = null;
  window.addEventListener("load", function () { fit(); });  // fonts and icons in
  window.addEventListener("resize", function () {
    if (refit) clearTimeout(refit);
    refit = setTimeout(fit, 150);
  });
  document.addEventListener("htmx:afterSwap", function (event) {
    stale(false);
    place(event.target);
    fit();
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
    if (mode) applyLook(mode.getAttribute("data-look"));
  }

  // F52b: the look. The server says "light", "dark" or "auto" (on <html>, and again with
  // the night part every minute, so "Dark in the evening" turns at its time); "auto" follows
  // the frame's own dark theme, and changes with it.
  var frameDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function applyLook(look) {
    var root = document.documentElement;
    if (look) root.setAttribute("data-look", look);
    look = root.getAttribute("data-look") || "light";
    var dark = look === "dark" || (look === "auto" && !!frameDark && frameDark.matches);
    root.classList.toggle("dark", dark);
    var colors = { light: "#e8ece6", dark: "#111317" };
    document.querySelectorAll('meta[name="theme-color"]:not([media])').forEach(function (m) {
      m.setAttribute("content", dark ? colors.dark : colors.light);
    });
  }
  if (frameDark && frameDark.addEventListener) {
    frameDark.addEventListener("change", function () { applyLook(null); });
  }
  function wake(on) {
    if (awake) { clearTimeout(awake); awake = null; }
    document.body.classList.toggle("awake", on);
    if (on) awake = setTimeout(function () { wake(false); }, 120000);
    if (on) fit();  // F58c: hidden at night, the columns had no height to fit into
  }
  document.addEventListener("pointerdown", function () {
    if (document.body.classList.contains("night")) wake(true);
  });

  // F52a: full screen on the first touch. Chrome allows it only from a touch, so a frame
  // that opens the wall as a plain shortcut or a tab gets there on its first one, and again
  // after Back or a swipe has left it. The touch still does what it was for. The root
  // element, not body, so the page's scaling and background hold.
  function shownAs() {
    if (document.fullscreenElement) return "fullscreen-api";
    var modes = ["fullscreen", "standalone"];
    for (var i = 0; i < modes.length; i++) {
      if (window.matchMedia && window.matchMedia("(display-mode: " + modes[i] + ")").matches) {
        return modes[i];
      }
    }
    return "browser";
  }
  function fullScreen() {
    var root = document.documentElement;
    if (shownAs() === "fullscreen" || document.fullscreenElement || !root.requestFullscreen) return;
    root.requestFullscreen({ navigationUI: "hide" }).catch(function () {});
  }
  document.addEventListener("pointerdown", fullScreen);
  // Each poll says how the frame shows the wall, for Wall frames.
  document.addEventListener("htmx:configRequest", function (event) {
    event.detail.headers["Themi-Wall-Display"] = shownAs();
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
    fit();
    setInterval(tick, 60000);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/wall/sw.js", { scope: "/wall" }).catch(function () {});
    }
  });
})();
