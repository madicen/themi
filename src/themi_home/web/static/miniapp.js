// CK10: the session pages' bridge to Telegram, when they're open as its Mini App. Not
// Telegram's own script: the page carries a session token and its CSP stays 'self', so this
// speaks Telegram's Mini App events (core.telegram.org/api/web-events) itself. Outside
// Telegram it sends nothing. The cook screen asks for full screen and turns off swipe-down
// to close (a wiped screen shouldn't close it); the body double page only expands.
(function () {
  "use strict";
  var root = document.documentElement;
  var hash = new URLSearchParams(location.hash.slice(1));
  var KEY = "themi_tg";
  var known = null;
  try { known = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (e) { /* storage off */ }
  var platform = hash.get("tgWebAppPlatform") || (known && known.platform) || "";
  var version = hash.get("tgWebAppVersion") || (known && known.version) || "6.0";
  var inTelegram = !!(platform || window.TelegramWebviewProxy);
  if (inTelegram) {
    try { sessionStorage.setItem(KEY, JSON.stringify({ platform: platform || "unknown", version: version })); }
    catch (e) { /* storage off */ }
  }

  function atLeast(want) {
    var have = version.split("."), need = want.split(".");
    for (var i = 0; i < Math.max(have.length, need.length); i++) {
      var a = Number(have[i] || 0), b = Number(need[i] || 0);
      if (a !== b) return a > b;
    }
    return true;
  }

  function send(type, data) {
    if (!inTelegram) return;
    var body = data === undefined ? null : data;
    try {
      if (window.TelegramWebviewProxy && window.TelegramWebviewProxy.postEvent) {
        window.TelegramWebviewProxy.postEvent(type, JSON.stringify(body));
      } else if (window.external && "notify" in window.external) {
        window.external.notify(JSON.stringify({ eventType: type, eventData: body }));
      } else if (window.parent !== window) {
        window.parent.postMessage(JSON.stringify({ eventType: type, eventData: body }), "*");
      }
    } catch (e) { /* nothing more to do */ }
  }

  // What Telegram sends back: the mobile apps call Telegram.WebView.receiveEvent; the web
  // version posts a message to the frame.
  var listeners = [];
  var state = { fullscreen: false };
  function px(n) { return (Number(n) || 0) + "px"; }
  function insets(prefix, data) {
    ["top", "bottom", "left", "right"].forEach(function (side) {
      root.style.setProperty("--tg-" + prefix + "-" + side, px(data && data[side]));
    });
  }
  function receive(type, data) {
    if (type === "safe_area_changed") insets("safe", data);
    else if (type === "content_safe_area_changed") insets("content", data);
    else if (type === "fullscreen_changed") state.fullscreen = !!(data && data.is_fullscreen);
    else if (type === "fullscreen_failed" && data && data.error === "ALREADY_FULLSCREEN") state.fullscreen = true;
    else return;
    root.classList.toggle("tg-fullscreen", state.fullscreen);
    listeners.forEach(function (fn) { try { fn(type, data); } catch (e) { /* one listener */ } });
  }
  if (inTelegram) {
    window.Telegram = window.Telegram || {};
    var earlier = window.Telegram.WebView && window.Telegram.WebView.receiveEvent;
    window.Telegram.WebView = window.Telegram.WebView || {};
    window.Telegram.WebView.receiveEvent = function (type, data) {
      receive(type, data);
      if (earlier) earlier(type, data);
    };
    window.addEventListener("message", function (event) {
      if (event.source !== window.parent) return;
      try {
        var m = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
        if (m && m.eventType) receive(m.eventType, m.eventData);
      } catch (e) { /* not Telegram's */ }
    });
    root.classList.add("in-telegram");
  }

  var canFullscreen = inTelegram && atLeast("8.0");
  window.themiMiniApp = {
    inTelegram: inTelegram,
    canFullscreen: canFullscreen,
    isFullscreen: function () { return state.fullscreen; },
    toggleFullscreen: function () {
      if (!canFullscreen) return;
      send(state.fullscreen ? "web_app_exit_fullscreen" : "web_app_request_fullscreen");
    },
    onChange: function (fn) { listeners.push(fn); },
    send: send
  };

  if (!inTelegram) return;

  // F40c, idea #193: "Open in browser" opens this page in the phone's own browser, signed in
  // with a fresh one-time ticket (the page's own session asks for it).
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest(".open-in-browser");
    if (!button || button.disabled) return;
    var body = document.body;
    var headers = { "X-CSRF-Token": body.dataset.csrf || "" };
    if (body.dataset.session) headers["X-Themi-Session"] = body.dataset.session;
    button.disabled = true;
    fetch("/session/ticket", { method: "POST", credentials: "same-origin", headers: headers })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (t) {
        button.disabled = false;
        if (t && t.ticket) {
          send("web_app_open_link", { url: location.origin + "/session?ticket=" + encodeURIComponent(t.ticket) });
        }
      }, function () { button.disabled = false; });
  });

  send("web_app_ready");
  send("web_app_expand");
  if (!document.body || !document.body.classList.contains("cook-page")) return;
  if (atLeast("7.7")) send("web_app_setup_swipe_behavior", { allow_vertical_swipe: false });
  if (canFullscreen) {
    send("web_app_request_safe_area");
    send("web_app_request_content_safe_area");
    send("web_app_request_fullscreen");
  }
})();
