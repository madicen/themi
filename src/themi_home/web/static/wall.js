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
    // F64h: the day planner, down the screen: top and height, and overlaps side by side
    root.querySelectorAll("[data-y]").forEach(function (el) {
      el.style.top = el.getAttribute("data-y") + "%";
    });
    root.querySelectorAll("[data-h]").forEach(function (el) {
      el.style.height = el.getAttribute("data-h") + "%";
    });
    root.querySelectorAll("[data-cols]").forEach(function (el) {
      var cols = Number(el.getAttribute("data-cols")) || 1;
      var col = Number(el.getAttribute("data-col")) || 0;
      el.style.left = (col * 100) / cols + "%";
      el.style.width = 100 / cols + "%";
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

  function tickPlanner() {  // F64h: today's planner keeps its now line moving too
    var day = document.querySelector(".pl[data-start]");
    var line = day && day.querySelector(".pl-now");
    if (!line) return;
    var start = Date.parse(day.getAttribute("data-start"));
    var end = Date.parse(day.getAttribute("data-end"));
    var at = Math.min(Math.max((Date.now() - start) / (end - start), 0), 1) * 100;
    line.style.top = at + "%";
    day.querySelectorAll(".pl-past").forEach(function (el) { el.style.height = at + "%"; });
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
    // F60e: "0" is a body double session going on: it stays until closed by hand.
    if (sheet.getAttribute("data-close-after") === "0") { idle = null; return; }
    var seconds = Number(sheet.getAttribute("data-close-after")) || 120;
    idle = setTimeout(closeView, seconds * 1000);
  }
  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest("[data-close]")) closeView();
  });
  document.addEventListener("pointerdown", function () { if (idle) watchView(); });

  // F59g (idea #257): the Talk sheet's mic, only where the frame can record. A tap starts,
  // a second (or 30 s) stops and sends the clip; the answer replaces the sheet.
  // F60d (idea #264): it says what it's doing: listening (red, a stop square, "Send", a
  // pulsing dot and the seconds), working ("Working it out…") and what went wrong. Cancel
  // throws a clip away.
  var LIMIT = 30;
  var recorder = null, cancelled = false, counting = null, busy = false;
  function canRecord() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }
  function showMics(root) {
    if (!canRecord()) return;
    root.querySelectorAll("[data-talk-mic]").forEach(function (b) { b.hidden = false; });
  }
  function talkStatus(text, kind) {
    var line = document.querySelector("[data-talk-status]");
    if (!line) return;
    line.textContent = text;
    line.className = "talk-status" + (kind ? " " + kind : "");
  }
  function mmss(seconds) {
    return Math.floor(seconds / 60) + ":" + ("0" + (seconds % 60)).slice(-2);
  }
  function micState(button, state) {
    var form = button.closest("form");
    var words = button.querySelector(".talk-mic-words");
    var cancel = form && form.querySelector("[data-talk-cancel]");
    button.classList.toggle("on", state === "listening");
    button.classList.toggle("busy", state === "working");
    button.disabled = state === "working";
    button.setAttribute("aria-pressed", state === "listening" ? "true" : "false");
    button.setAttribute("aria-label", state === "listening" ? "Send: tap when you're done"
      : state === "working" ? "Working it out" : "Talk: tap to start, tap again to send");
    if (words) words.textContent = state === "listening" ? "Send" : "Talk";
    if (cancel) cancel.hidden = state !== "listening";
    if (form) {
      form.querySelectorAll("input[name=text], button.primary").forEach(function (el) {
        el.disabled = state !== "idle";
      });
    }
  }
  function listening(seconds) {
    var left = LIMIT - seconds;
    talkStatus("Listening… tap Send when you're done · " +
      (left <= 5 ? left + " s left" : mmss(seconds) + " of " + mmss(LIMIT)), "listening");
  }
  function missed() {
    talkStatus("I didn't catch that. Try again, or type it.", "missed");
  }
  function sendClip(button, blob) {
    var form = new FormData();
    form.append("member", button.getAttribute("data-member"));
    form.append("audio", blob, "clip.webm");
    var token = (JSON.parse(document.body.getAttribute("hx-headers") || "{}"))["X-CSRF-Token"] || "";
    busy = true;
    micState(button, "working");
    talkStatus("Working it out…", "working");
    fetch("/wall/say", { method: "POST", body: form, headers: { "X-CSRF-Token": token, "HX-Request": "true" } })
      .then(function (r) {
        if (!r.ok) throw new Error("refused " + r.status);
        return r.text();
      })
      .then(function (html) {
        busy = false;
        var view = document.getElementById("wall-view");
        if (!view) return;
        view.innerHTML = html;
        if (window.htmx) window.htmx.process(view);
        showMics(view);
      })
      .catch(function () {
        busy = false;
        micState(button, "idle");
        missed();
      });
  }
  document.addEventListener("click", function (event) {
    var cancel = event.target.closest && event.target.closest("[data-talk-cancel]");
    if (cancel) {
      event.preventDefault();
      if (recorder) { cancelled = true; recorder.stop(); }
      return;
    }
    var button = event.target.closest && event.target.closest("[data-talk-mic]");
    if (!button) return;
    event.preventDefault();
    if (busy) return;
    if (recorder) { recorder.stop(); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var chunks = [], seconds = 0;
      cancelled = false;
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        if (counting) { clearInterval(counting); counting = null; }
        var type = recorder.mimeType || "audio/webm";
        recorder = null;
        micState(button, "idle");
        if (cancelled) { talkStatus("", ""); return; }
        if (chunks.length) sendClip(button, new Blob(chunks, { type: type }));
        else missed();
      };
      recorder.start();
      micState(button, "listening");
      listening(0);
      counting = setInterval(function () {
        seconds += 1;
        if (seconds >= LIMIT) { if (recorder) recorder.stop(); return; }
        listening(seconds);
      }, 1000);
    }).catch(function () {
      talkStatus("The frame didn't let Themi use the microphone. Typing works.", "missed");
      button.hidden = true;
    });
  });
  document.addEventListener("htmx:afterSwap", function (event) { showMics(event.target); });

  // F60e (idea #263): the body double's timer counts between the server's redraws (from
  // its end or start and the server's now), and a finished session closes after 10 s.
  var skew = 0;
  function focusTimers() {
    document.querySelectorAll(".focus-timer[data-timer]").forEach(function (el) {
      var now = el.getAttribute("data-now");
      if (now && !el.hasAttribute("data-skew")) {
        skew = Date.parse(now) - Date.now();
        el.setAttribute("data-skew", "1");
      }
      var at = Date.now() + skew;
      var down = el.getAttribute("data-timer") === "down";
      var mark = Date.parse(el.getAttribute(down ? "data-to" : "data-from"));
      if (isNaN(mark)) return;
      var s = Math.max(0, Math.round((down ? mark - at : at - mark) / 1000));
      var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
      el.textContent = (h ? h + ":" + ("0" + m).slice(-2) : m) + ":" + ("0" + sec).slice(-2);
    });
  }
  setInterval(focusTimers, 1000);
  var ending = null;
  document.addEventListener("htmx:afterSwap", function () {
    if (document.querySelector("#wall-view [data-focus-finished], #wall-view [data-focus-over]")) {
      if (!ending) ending = setTimeout(function () { ending = null; closeView(); }, 10000);
      stopMusic();  // the session's over: its loop stops with it
    }
    // Closed by hand and then ended elsewhere: the columns' redraw has no chip left.
    if (!document.querySelector(".wall-focus-chip, #wall-view [data-focus-running]")) stopMusic();
    musicShown();
  });

  // F60e: the built-in loop plays from the frame through #wall-music, which lives outside
  // the sheet so a tap or a redraw doesn't stop it. Nothing plays until Play is tapped.
  // The choice and volume are kept as /session keeps them (POST /wall/focus/music).
  function player() { return document.getElementById("wall-music"); }
  function musicBox() { return document.querySelector("#wall-view [data-focus-music]"); }
  function saveMusic(fields) {
    var box = musicBox();
    if (!box) return;
    fields.member = box.getAttribute("data-member");
    var token = (JSON.parse(document.body.getAttribute("hx-headers") || "{}"))["X-CSRF-Token"] || "";
    fetch("/wall/focus/music", {
      method: "POST",
      headers: { "X-CSRF-Token": token, "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(fields).toString()
    }).then(function () {}, function () {});
  }
  function chosenSrc(box) {
    var sound = box.querySelector("[data-music-sound]");
    return sound ? sound.options[sound.selectedIndex].getAttribute("data-src") : "";
  }
  function musicShown() {
    var box = musicBox(), audio = player();
    if (!box || !audio) return;
    var on = !audio.paused;
    var play = box.querySelector("[data-music-play]");
    play.textContent = on ? "Pause" : "Play";
    play.setAttribute("aria-pressed", on ? "true" : "false");
    var volume = box.querySelector("[data-music-volume]");
    if (volume) audio.volume = Number(volume.value) / 100;
  }
  function stopMusic() {
    var audio = player();
    if (audio && !audio.paused) audio.pause();
  }
  document.addEventListener("click", function (event) {
    var play = event.target.closest && event.target.closest("[data-music-play]");
    if (!play) return;
    var box = musicBox(), audio = player();
    if (!box || !audio) return;
    if (audio.paused) {
      var src = chosenSrc(box);
      if (src && audio.getAttribute("src") !== src) audio.setAttribute("src", src);
      audio.play().then(function () { musicShown(); saveMusic({ played: "1" }); },
                        function () { musicShown(); });
    } else {
      audio.pause();
      musicShown();
    }
  });
  document.addEventListener("change", function (event) {
    var box = musicBox(), audio = player();
    if (!box || !audio || !box.contains(event.target)) return;
    if (event.target.matches("[data-music-sound]")) {
      var playing = !audio.paused;
      audio.setAttribute("src", chosenSrc(box));
      if (playing) audio.play().then(function () {}, function () { musicShown(); });
      saveMusic(playing ? { sound: event.target.value, played: "1" } : { sound: event.target.value });
    } else if (event.target.matches("[data-music-volume]")) {
      saveMusic({ volume: event.target.value });
    }
  });
  document.addEventListener("input", function (event) {
    var audio = player();
    if (audio && event.target.matches && event.target.matches("#wall-view [data-music-volume]")) {
      audio.volume = Number(event.target.value) / 100;
    }
  });

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
    // F64g: an Undo bar goes after its few seconds
    event.target.querySelectorAll("[data-undo-for]").forEach(function (bar) {
      setTimeout(function () { bar.remove(); }, Number(bar.dataset.undoFor) * 1000);
    });
  });
  // WL6: the night. The night part says whether it's night (data-night); a touch shows
  // the full screen until it's left alone for two minutes.
  var awake = null;
  function nightMode() {
    var mode = document.querySelector("#wall-night .wall-night-mode");
    var night = mode && mode.getAttribute("data-night") === "1" &&
      !document.querySelector("#wall-view [data-focus-running]");  // F60e: not mid-session
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
    setInterval(function () { tick(); tickPlanner(); }, 60000);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/wall/sw.js", { scope: "/wall" }).catch(function () {});
    }
  });
})();
