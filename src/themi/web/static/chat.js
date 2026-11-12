// WC1: the website chat (/chat). htmx brings the conversation; this keeps it scrolled to
// the newest message, skips polling while the tab is hidden, handles ↩ Reply without a
// reload, sends on Enter (Shift+Enter for a new line) and clears the box once it's sent.
(function () {
  "use strict";
  const form = document.getElementById("say");
  if (!form) return;
  const text = form.querySelector("textarea[name=text]");
  const replyTo = form.querySelector("input[name=reply_to]");
  const replying = form.querySelector(".chat-replying");
  const replyingQuote = form.querySelector(".chat-replying-quote");
  let follow = true; // the newest message was in view before the last swap

  function nearBottom() {
    return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 120;
  }

  function toBottom() {
    window.scrollTo(0, document.documentElement.scrollHeight);
  }

  function setReply(id, quote) {
    replyTo.value = id || "";
    replyingQuote.textContent = quote || "";
    replying.hidden = !id;
    if (id) text.focus();
  }

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    // The poll waits while nobody is looking; sends and taps always go.
    const elt = event.detail.elt;
    if (elt && elt.id === "chat-log" && document.hidden) event.preventDefault();
  });

  document.body.addEventListener("htmx:beforeSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "chat-log") follow = nearBottom();
  });

  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (event.detail.target && event.detail.target.id === "chat-log" && follow) toBottom();
  });

  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (event.detail.elt === form && event.detail.successful) {
      form.querySelector("textarea[name=text]").value = "";
      setReply(null, "");
      follow = true;
      toBottom();
    }
  });

  document.addEventListener("click", function (event) {
    const reply = event.target.closest("a.chat-reply");
    if (reply) {
      event.preventDefault();
      setReply(reply.dataset.reply, reply.dataset.quote);
      return;
    }
    if (event.target.closest("a.chat-replying-cancel")) {
      event.preventDefault();
      setReply(null, "");
    }
  });

  text.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (text.value.trim()) form.requestSubmit();
    }
  });

  toBottom();
})();
