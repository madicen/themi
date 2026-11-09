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
    var soonest = document.querySelector(".cook-soonest");
    if (soonest) soonest.textContent = soonest.dataset.ends ? words(Date.parse(soonest.dataset.ends) - now) : "";
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
        var open = {};
        box.querySelectorAll("details[data-keep-open]").forEach(function (d) { open[d.dataset.keepOpen] = d.open; });
        box.innerHTML = html;
        box.querySelectorAll("details[data-keep-open]").forEach(function (d) { if (open[d.dataset.keepOpen]) d.open = true; });
        drawer(drawerOpen);
        alerts();
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
    looks(state);
    company(state);
    if (window.themiCook && window.themiCook.onState) window.themiCook.onState(state);
  }

  function poll() {
    fetch("/session/state", { credentials: "same-origin", cache: "no-store", headers: auth() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) redraw(s); }, function () {});
  }

  // Every tap is a form posted with fetch (with the session header), then the state redrawn.
  // Each form has a hidden input named "action", which shadows form.action: read the attribute.
  function post(form, extra, submitter) {
    var data = new URLSearchParams(new FormData(form));
    if (submitter && submitter.name) data.set(submitter.name, submitter.value);
    if (extra) Object.keys(extra).forEach(function (k) { data.set(k, extra[k]); });
    return fetch(form.getAttribute("action"), {
      method: "POST", body: data.toString(), credentials: "same-origin",
      headers: auth({ "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" })
    }).then(function (r) {
      if (!r.ok) report("cook tap " + data.get("action") + " answered " + r.status);
      return r.ok ? r.json() : null;
    }).then(function (s) {
      if (s) { say(s.said); redraw(s); if (s.open_chat) chatOpen(true); }
      return s;
    }, function (e) { report("cook tap failed: " + e); });
  }

  // CK3: a fired timer chimes and pulses the screen (slowly, never a strobe), again every
  // 30 seconds, until its card is tapped. Under prefers-reduced-motion, a steady border.
  var alerting = null;
  function chime(volume) {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx || volume <= 0) return;
    try {
      var ctx = chime.ctx || (chime.ctx = new Ctx());
      if (ctx.state === "suspended") ctx.resume();
      [660, 880].forEach(function (hz, n) {
        var osc = ctx.createOscillator(), gain = ctx.createGain(), at = ctx.currentTime + n * 0.35;
        osc.frequency.value = hz;
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, volume / 100 * 0.6), at + 0.03);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.9);
        osc.connect(gain); gain.connect(ctx.destination);
        osc.start(at); osc.stop(at + 1);
      });
    } catch (e) { report("chime: " + e); }
  }
  function ring() {
    var shown = main();
    var volume = shown ? Number(shown.dataset.chime || 70) : 70;
    (window.themiCook.playChime || chime)(volume);
    body.dataset.rings = String(Number(body.dataset.rings || 0) + 1);
    var pulse = document.querySelector(".cook-pulse");
    if (pulse) { pulse.classList.remove("on"); void pulse.offsetWidth; pulse.classList.add("on"); }
  }
  function alerts() {
    var fired = !!document.querySelector(".cook-timer[data-fired]");
    body.classList.toggle("cook-alerting", fired);
    if (fired && alerting === null) {
      ring();
      alerting = setInterval(ring, window.themiCook.alertEvery || 30000);
    } else if (!fired && alerting !== null) {
      clearInterval(alerting);
      alerting = null;
    }
  }

  // CK7: A- and A+, kept as a preference; the theme and size follow the state
  function looks(state) {
    if (!state.view) return;
    body.dataset.theme = state.view.theme;
    body.dataset.textSize = String(state.view.text_size);
  }
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.closest || !form.closest(".cook-size")) return;
    event.preventDefault();
    var data = new URLSearchParams(new FormData(form));
    if (event.submitter && event.submitter.name) data.set(event.submitter.name, event.submitter.value);
    fetch(form.getAttribute("action"), {
      method: "POST", body: data.toString(), credentials: "same-origin",
      headers: auth({ "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" })
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) { looks(s); redraw(s); } }, function (e) { report("size failed: " + e); });
  });

  // CK8: push-to-talk, only where the browser recognises speech and they've turned it on.
  // Hold to talk, or tap: one phrase a press. The words go to /session/cook/{id}/say.
  var heardTimer = null;
  function heard(text) {
    var el = document.querySelector(".cook-heard");
    if (!el) return;
    el.textContent = text ? "\u201c" + text + "\u201d" : "";
    clearTimeout(heardTimer);
    heardTimer = setTimeout(function () { el.textContent = ""; }, 4000);
  }
  function sayWords(text) {
    var shown = main();
    if (!shown || !text) return;
    heard(text);
    fetch("/session/cook/" + shown.dataset.session + "/say", {
      method: "POST", credentials: "same-origin",
      body: new URLSearchParams({ csrf: body.dataset.csrf, text: text }).toString(),
      headers: auth({ "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" })
    }).then(function (r) {
      if (!r.ok) report("say answered " + r.status);
      return r.ok ? r.json() : null;
    }).then(function (s) {
      if (!s) return;
      say(s.said); redraw(s);
      if (s.open_chat) chatOpen(true);
    }, function (e) { report("say failed: " + e); });
  }
  function setupVoice() {
    var mic = document.querySelector(".cook-mic");
    if (!mic) return;
    var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    mic.hidden = !Rec || mic.dataset.on !== "1";
    if (mic.hidden || mic.dataset.ready) return;
    mic.dataset.ready = "1";
    var rec = null, listening = false, downAt = 0;
    function start() {
      var Now = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (listening || !Now) return;
      try {
        rec = new Now();
        rec.lang = document.documentElement.lang || "en";
        rec.continuous = false;
        rec.interimResults = false;
        rec.maxAlternatives = 1;
        rec.onresult = function (e) {
          var said = e.results && e.results[0] && e.results[0][0] ? e.results[0][0].transcript : "";
          sayWords(String(said).trim());
        };
        rec.onend = function () { listening = false; mic.setAttribute("aria-pressed", "false"); };
        rec.onerror = function (e) { listening = false; mic.setAttribute("aria-pressed", "false"); if (e && e.error !== "no-speech") report("voice: " + e.error); };
        listening = true;
        mic.setAttribute("aria-pressed", "true");
        rec.start();
      } catch (e) { listening = false; report("voice start: " + e); }
    }
    mic.addEventListener("pointerdown", function () { downAt = Date.now(); start(); });
    mic.addEventListener("pointerup", function () {  // held: stop when let go; tapped: one phrase
      if (rec && listening && Date.now() - downAt > 400) rec.stop();
    });
    mic.addEventListener("click", function (e) { if (e.detail === 0) start(); });  // keyboard
  }

  // CK3: the chime's volume, kept for next time (a preference)
  document.addEventListener("change", function (event) {
    var t = event.target;
    if (!t.closest || !t.closest(".cook-chime")) return;
    var form = t.closest("form"), shown = main();
    if (shown) shown.dataset.chime = t.value;
    fetch(form.getAttribute("action"), {
      method: "POST", credentials: "same-origin", body: new URLSearchParams(new FormData(form)).toString(),
      headers: auth({ "Content-Type": "application/x-www-form-urlencoded" })
    }).then(function () {}, function () {});
  });

  // CK5: the company bar, kept live from the state: the scene, Themi's line, Ask Themi
  function company(state) {
    var scene = document.querySelector(".cook-scene");
    if (scene && state.scene) scene.dataset.state = state.scene;
    var line = document.querySelector('[data-live="line"]');
    if (line && line.textContent !== state.line) line.textContent = state.line || "";
    var list = document.querySelector(".cook-chat ol");
    var chat = state.chat || [];
    if (list && list.dataset.count !== String(chat.length)) {
      list.dataset.count = String(chat.length);
      list.textContent = "";
      chat.forEach(function (said) {
        var li = document.createElement("li");
        li.className = said.who;
        li.textContent = said.text;
        list.appendChild(li);
      });
      list.scrollTop = list.scrollHeight;
    }
  }
  function chatOpen(on) {
    var panel = document.querySelector(".cook-chat");
    if (!panel) return;
    panel.hidden = !on;
    body.classList.toggle("drawer-open", on || drawerOpen);
    if (on) { var input = panel.querySelector("input[name=text]"); if (input) input.focus(); }
  }
  document.addEventListener("click", function (event) {
    var t = event.target;
    if (!t.closest) return;
    if (t.closest(".cook-chat-open")) chatOpen(true);
    else if (t.closest(".cook-chat-close")) chatOpen(false);
  });
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.closest) return;
    if (form.closest(".cook-chat")) {
      event.preventDefault();
      var data = new URLSearchParams(new FormData(form)).toString();
      form.reset();
      fetch(form.getAttribute("action"), {
        method: "POST", body: data, credentials: "same-origin",
        headers: auth({ "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" })
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (s) { if (s) redraw(s); }, function (e) { report("ask failed: " + e); });
    } else if (form.closest(".cook-spotify")) {
      event.preventDefault();
      var said = document.querySelector(".cook-spotify .session-spotify-said");
      var sent = new URLSearchParams(new FormData(form));
      sent.set("action", event.submitter && event.submitter.value ? event.submitter.value : "play");
      fetch(form.getAttribute("action"), {
        method: "POST", body: sent.toString(), credentials: "same-origin",
        headers: auth({ "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" })
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (s) { if (said) said.textContent = s && s.said ? s.said : "That didn't reach Spotify. Try again in a moment."; },
              function () { if (said) said.textContent = "That didn't reach Spotify. Try again in a moment."; });
    }
  });

  // CK5: the built-in loop, as on the body double page; nothing plays until they tap Play
  function music() {
    var box = document.querySelector(".cook-music");
    if (!box) return;
    var audio = box.querySelector("audio"), play = box.querySelector(".session-play");
    var sound = box.querySelector("select"), volume = box.querySelector("input[type=range]");
    audio.volume = Number(volume.value) / 100;
    function save(fields) {
      fields.csrf = body.dataset.csrf;
      fetch("/session/music", {
        method: "POST", credentials: "same-origin",
        headers: auth({ "Content-Type": "application/x-www-form-urlencoded" }),
        body: new URLSearchParams(fields).toString()
      }).then(function () {}, function () {});
    }
    function shown(on) { play.textContent = on ? "Pause" : "Play"; play.setAttribute("aria-pressed", on ? "true" : "false"); }
    play.addEventListener("click", function () {
      if (audio.paused) audio.play().then(function () { shown(true); }, function () { shown(false); });
      else { audio.pause(); shown(false); }
    });
    sound.addEventListener("change", function () {
      var playing = !audio.paused;
      audio.src = sound.options[sound.selectedIndex].dataset.src;
      if (playing) audio.play().then(function () {}, function () { shown(false); });
      save({ sound: sound.value });
    });
    volume.addEventListener("input", function () { audio.volume = Number(volume.value) / 100; });
    volume.addEventListener("change", function () { save({ volume: volume.value }); });
  }

  // CK2: what a tap says once ("Now for 6."), for a few seconds
  var saidTimer = null;
  function say(text) {
    var el = document.querySelector(".cook-said");
    if (!el || !text) return;
    el.textContent = text;
    el.hidden = false;
    clearTimeout(saidTimer);
    saidTimer = setTimeout(function () { el.hidden = true; }, 4000);
  }

  // CK2: the All ingredients drawer, kept open across redraws
  var drawerOpen = false;
  function drawer(on) {
    drawerOpen = on;
    var box = document.querySelector(".cook-drawer");
    if (box) box.hidden = !on;
    body.classList.toggle("drawer-open", on && !!box);
  }
  document.addEventListener("click", function (event) {
    var t = event.target;
    if (!t.closest) return;
    if (t.closest(".cook-all-open")) drawer(true);
    else if (t.closest(".cook-drawer-close")) drawer(false);
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.closest || !form.closest("#cook")) return;
    if (form.dataset.local || !form.closest("#cook")) return;  // a form handled elsewhere
    event.preventDefault();
    post(form, null, event.submitter);
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
  window.themiCook.alerts = alerts;
  window.themiCook.chatOpen = chatOpen;
  window.themiCook.setupVoice = setupVoice;
  window.themiCook.sayWords = sayWords;
  window.themiCook.post = post;
  window.themiCook.poll = poll;
  window.themiCook.view = view;
  window.themiCook.auth = auth;
  window.themiCook.report = report;
  window.themiCook.now = function () { return Date.now() + offset; };
  window.themiCook.drawer = drawer;
  window.themiCook.say = say;

  document.addEventListener("visibilitychange", function () { hold(); if (document.visibilityState === "visible") poll(); });
  hold();
  setupVoice();
  music();
  alerts();
  tick();
  setInterval(tick, 1000);
  setInterval(poll, POLL);
})();
