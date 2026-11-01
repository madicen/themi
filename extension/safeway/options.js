// The options page (35d): Themi's address and the helper token. Host access to that
// address is asked for here, when the person clicks Connect, and for nothing else.
(function () {
  const storage = chrome.storage.local;
  const $ = (id) => document.getElementById(id);
  const status = $("status");

  async function show() {
    const s = await storage.get(["themiUrl", "themiToken", "themiStatus"]);
    $("url").value = s.themiUrl || "";
    $("token").value = "";
    $("token").placeholder = s.themiToken ? "Saved (paste a new one to replace it)" : "swh_...";
    if (s.themiStatus === "revoked") status.textContent = "Themi disconnected this helper. Make a new token and connect again.";
    else if (s.themiUrl && s.themiToken) status.textContent = "Connected to " + s.themiUrl + ".";
    else status.textContent = "Not connected.";
  }

  $("save").addEventListener("click", async () => {
    let base;
    try {
      base = ThemiLink.normalizeAddress($("url").value);
    } catch (e) {
      status.textContent = e.message;
      return;
    }
    const saved = await storage.get("themiToken");
    const token = $("token").value.trim() || saved.themiToken || "";
    if (!/^swh_[\w-]{20,}$/.test(token)) {
      status.textContent = "Paste the token from Themi's Safeway page. It starts with swh_.";
      return;
    }
    // Asked while handling the click: Chrome only shows the prompt for a user gesture.
    const granted = await chrome.permissions.request({ origins: [ThemiLink.originPattern(base)] });
    if (!granted) {
      status.textContent = "The helper needs permission to reach " + base + " to take carts from Themi.";
      return;
    }
    await storage.set({ themiUrl: base, themiToken: token, themiStatus: "connected" });
    status.textContent = "Checking...";
    const res = await chrome.runtime.sendMessage({ type: "themi-test" });
    await show();
    status.textContent = res && res.ok ? "Connected to " + base + "." : (res && res.detail) || "Couldn't reach Themi.";
    if (res && res.ok) chrome.runtime.sendMessage({ type: "themi-connected" });
  });

  $("disconnect").addEventListener("click", async () => {
    const s = await storage.get("themiUrl");
    await storage.remove(["themiUrl", "themiToken", "themiStatus", "themiBusy"]);
    if (s.themiUrl) await chrome.permissions.remove({ origins: [ThemiLink.originPattern(s.themiUrl)] }).catch(() => {});
    await show();
  });

  show();
})();
