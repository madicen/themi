// BD3a: the body double session page. The server is the truth: every 5 seconds the page
// asks /session/state and redraws; the timer counts in between from the server's times.
(function () {
  "use strict";
  var body = document.body;
  var POLL = 5000;
  var offset = 0; // server time minus this browser's time, in ms
  var timer = null;

  function signIn() {
    var hash = new URLSearchParams(location.hash.slice(1));
    var data = hash.get("tgWebAppData");
    var help = document.getElementById("sign-in-help");
    if (!data) { if (help) help.hidden = false; return; }
    fetch("/session/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ init_data: data }).toString(),
      credentials: "same-origin"
    }).then(function (r) {
      if (r.status === 204) { location.replace("/session"); }
      else if (help) { help.hidden = false; }
    }, function () { if (help) help.hidden = false; });
  }

  function two(n) { return (n < 10 ? "0" : "") + n; }
  function words(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? h + ":" + two(m) + ":" + two(s % 60) : m + ":" + two(s % 60);
  }

  function tick() {
    var el = document.querySelector(".session-timer");
    if (!el) return;
    var now = Date.now() + offset;
    if (el.dataset.timer === "down" && el.dataset.to) {
      el.textContent = words(Date.parse(el.dataset.to) - now);
    } else if (el.dataset.from) {
      el.textContent = words(now - Date.parse(el.dataset.from));
    }
  }

  function redraw(state) {
    if (!state.active) { location.reload(); return; }
    offset = Date.parse(state.now) - Date.now();
    var moves = document.querySelector(".session-moves");
    if (!moves || String(state.id) !== moves.dataset.session) { location.reload(); return; }
    var fields = document.querySelectorAll("[data-field]");
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i].dataset.field;
      if (f === "mode_name") fields[i].textContent = state.mode_name.charAt(0).toUpperCase() + state.mode_name.slice(1);
      else if (f === "steps") fields[i].textContent = state.of ? "Step " + state.step + " of " + state.of : "";
      else if (state[f] !== undefined) fields[i].textContent = state[f];
    }
    var scene = document.querySelector(".session-scene");
    if (scene) {
      if (scene.dataset.mode !== state.mode) { location.reload(); return; }
      scene.dataset.phase = state.phase;
      scene.dataset.state = state.scene;
    }
    drawChat(state);
    drawPicture(state);
    var el = document.querySelector(".session-timer");
    if (el) {
      el.dataset.timer = state.timer.kind;
      el.dataset.to = state.timer.to || "";
      el.dataset.from = state.timer.from || "";
    }
    if (moves.dataset.seq !== String(state.seq)) {
      moves.dataset.seq = String(state.seq);
      moves.textContent = "";
      state.buttons.forEach(function (b, n) {
        var form = document.createElement("form");
        form.method = "post";
        form.action = "/session/" + state.id + "/act";
        [["csrf", body.dataset.csrf], ["seq", state.seq], ["action", b.action], ["mode", b.mode]]
          .forEach(function (pair) {
            var input = document.createElement("input");
            input.type = "hidden"; input.name = pair[0]; input.value = pair[1];
            form.appendChild(input);
          });
        var button = document.createElement("button");
        button.className = (n === 0 ? "primary " : "") + "big";
        button.textContent = b.label;
        form.appendChild(button);
        moves.appendChild(form);
      });
    }
    tick();
  }

  // BD4b: the step's picture, a soft placeholder while it's made, or the text alone
  function drawPicture(state) {
    var figure = document.querySelector(".session-picture");
    if (!figure) { if (state.picture) location.reload(); return; }
    var picture = state.picture || { status: "none" };
    figure.dataset.status = picture.status;
    var img = figure.querySelector("img");
    if (picture.url) { if (img.getAttribute("src") !== picture.url) img.src = picture.url; img.hidden = false; }
    else { img.hidden = true; img.removeAttribute("src"); }
  }

  // BD3b: chat on the page during a sprint's break
  function drawChat(state) {
    var open = document.querySelector(".session-chat-open");
    var panel = document.querySelector(".session-chat");
    if (!open || !panel) return;
    open.hidden = state.phase !== "break";
    if (state.phase !== "break") { showChat(false); return; }
    var list = panel.querySelector("ol");
    list.textContent = "";
    (state.chat || []).forEach(function (line) {
      var li = document.createElement("li");
      li.className = line.who;
      li.textContent = line.text;
      list.appendChild(li);
    });
    list.scrollTop = list.scrollHeight;
  }

  function showChat(on) {
    var panel = document.querySelector(".session-chat");
    if (!panel) return;
    panel.hidden = !on;
    body.classList.toggle("chatting", on);
    if (on) { var input = panel.querySelector("input[name=text]"); if (input) input.focus(); }
  }

  function onChat(event) {
    var form = event.target;
    if (!form.closest || !form.closest(".session-chat")) return false;
    event.preventDefault();
    var data = new URLSearchParams(new FormData(form)).toString();
    form.reset();
    fetch(form.action, {
      method: "POST", body: data, credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" }
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) redraw(s); }, function () {});
    return true;
  }

  function poll() {
    fetch("/session/state", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) redraw(s); }, function () {});
  }

  function onRedo(event) {
    var form = event.target;
    if (!form.closest || !form.closest(".session-redo")) return false;
    event.preventDefault();
    var data = new URLSearchParams(new FormData(form)).toString();
    form.reset();
    var figure = document.querySelector(".session-picture");
    if (figure) figure.dataset.status = "making";
    fetch(form.action, {
      method: "POST", body: data, credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" }
    }).then(function () {}, function () {});
    return true;
  }

  function onSubmit(event) {
    if (onChat(event) || onRedo(event)) return;
    var form = event.target;
    if (!form.closest || !form.closest(".session-moves")) return;
    event.preventDefault();
    fetch(form.action, {
      method: "POST",
      body: new URLSearchParams(new FormData(form)).toString(),
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
      credentials: "same-origin"
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) redraw(s); }, function () {});
  }

  // BD5a: the built-in loop; nothing plays until they tap Play (browsers insist anyway)
  function music() {
    var box = document.querySelector(".session-music");
    if (!box) return;
    var audio = box.querySelector("audio"), play = box.querySelector(".session-play");
    var sound = box.querySelector("select"), volume = box.querySelector("input[type=range]");
    audio.volume = Number(volume.value) / 100;
    function save(fields) {
      fields.csrf = body.dataset.csrf;
      fetch("/session/music", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(fields).toString()
      }).then(function () {}, function () {});
    }
    function shown(on) { play.textContent = on ? "Pause" : "Play"; play.setAttribute("aria-pressed", on ? "true" : "false"); }
    play.addEventListener("click", function () {
      if (audio.paused) {
        audio.play().then(function () { shown(true); save({ played: "1" }); }, function () { shown(false); });
      }
      else { audio.pause(); shown(false); }
    });
    sound.addEventListener("change", function () {
      var playing = !audio.paused;
      audio.src = sound.options[sound.selectedIndex].dataset.src;
      if (playing) audio.play().then(function () {}, function () { shown(false); });
      save(playing ? { sound: sound.value, played: "1" } : { sound: sound.value });
    });
    volume.addEventListener("input", function () { audio.volume = Number(volume.value) / 100; });
    volume.addEventListener("change", function () { save({ volume: volume.value }); });
  }

  var lock = null;
  function hold() { // keep the screen on, where the browser offers it
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    navigator.wakeLock.request("screen").then(function (l) { lock = l; }, function () {});
  }

  if (body.dataset.signedIn !== "1") { signIn(); return; }
  var first = document.querySelector(".session-timer");
  if (first && first.dataset.now) offset = Date.parse(first.dataset.now) - Date.now();
  document.addEventListener("submit", onSubmit);
  document.addEventListener("click", function (event) {
    var t = event.target;
    if (t.closest && t.closest(".session-chat-open")) showChat(true);
    if (t.closest && t.closest(".session-chat-close")) showChat(false);
  });
  document.addEventListener("visibilitychange", function () { hold(); if (document.visibilityState === "visible") poll(); });
  hold();
  music();
  tick();
  timer = setInterval(tick, 1000);
  setInterval(poll, POLL);
})();
