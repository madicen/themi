// The extension's side of a safeway.com tab. The popup asks it to fill the cart; it gets
// the page's values from page.js, runs the fill and keeps progress and results in
// chrome.storage.local so the popup can close and reopen.
(function () {
  const { createClient } = globalThis.ThemiSafeway;
  const { fillCart, alternatives, choose, createMemory } = globalThis.ThemiFill;
  const { parseList } = globalThis.ThemiList;

  const storage = chrome.storage.local;
  const memory = createMemory(storage);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let running = false;

  function cartId() {
    try {
      const saved = JSON.parse(localStorage.getItem("cartId") || "null");
      return saved && saved.abs ? String(saved.abs) : "";
    } catch (e) {
      return "";
    }
  }

  function pageContext() {
    return new Promise((resolve) => {
      const nonce = crypto.randomUUID();
      const done = (ctx) => {
        window.removeEventListener("message", onMessage);
        clearTimeout(timer);
        resolve(ctx);
      };
      const onMessage = (event) => {
        const msg = event.data;
        if (event.source === window && msg && msg.source === "themi-safeway-page" && msg.nonce === nonce) done(msg.ctx);
      };
      const timer = setTimeout(() => done(null), 3000);
      window.addEventListener("message", onMessage);
      window.postMessage({ source: "themi-safeway-ext", type: "context", nonce }, window.location.origin);
    });
  }

  async function client() {
    const ctx = await pageContext();
    if (!ctx || !ctx.storeId || !ctx.searchKey) throw new Error("The Safeway page hasn't finished loading. Try again in a moment.");
    return createClient({ ctx: { ...ctx, cartId: cartId() }, fetchFn: (url, init) => fetch(url, init), sleep });
  }

  async function fill(text) {
    const items = parseList(text);
    if (!items.length) return;
    running = true;
    try {
      await storage.set({ run: { state: "running", done: 0, total: items.length, item: items[0].name } });
      const result = await fillCart({
        items,
        client: await client(),
        memory,
        onProgress: (p) => storage.set({ run: { state: "running", ...p } }),
      });
      await storage.set({ run: { state: "done", at: Date.now(), result } });
    } catch (e) {
      await storage.set({ run: { state: "done", at: Date.now(), result: { added: [], notFound: [], outOfStock: [], failed: [], stopped: String(e.message || e) } } });
    } finally {
      running = false;
    }
  }

  chrome.runtime.onMessage.addListener((msg, sender, reply) => {
    if (sender.id !== chrome.runtime.id || !msg) return false;
    if (msg.type === "fill") {
      if (running) reply({ ok: false, detail: "Already filling the cart." });
      else {
        fill(String(msg.text || ""));
        reply({ ok: true });
      }
      return false;
    }
    if (msg.type === "alternatives") {
      client()
        .then((c) => alternatives({ item: String(msg.item), client: c, exclude: String(msg.exclude || "") }))
        .then((products) => reply({ ok: true, products }), (e) => reply({ ok: false, detail: String(e.message || e) }));
      return true;
    }
    if (msg.type === "choose") {
      if (!msg.product || !/^\d+$/.test(String(msg.product.id))) {
        reply({ ok: false, detail: "That isn't a Safeway product." });
        return false;
      }
      client()
        .then((c) => choose({ key: String(msg.key), qty: Number(msg.qty) || 1, product: msg.product, client: c, memory }))
        .then(reply, (e) => reply({ ok: false, detail: String(e.message || e) }));
      return true;
    }
    return false;
  });
})();
