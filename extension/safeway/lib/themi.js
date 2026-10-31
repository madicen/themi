// Talking to Themi (35d): the helper's address and token, the /api/safeway/ calls, and the
// shape of a job's results. Used by the service worker; pure enough to test with node.
(function (root) {
  class Revoked extends Error {
    constructor() {
      super("The helper's connection was revoked. Connect it again on Themi's Safeway page.");
      this.name = "Revoked";
    }
  }

  const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

  // Themi's address as typed: https anywhere, or http only on this computer. Returns the
  // base URL without a trailing slash; throws with a message for the options page.
  function normalizeAddress(text) {
    let url;
    try {
      url = new URL(String(text || "").trim());
    } catch {
      throw new Error("That isn't a web address. It looks like https://themi.example.com");
    }
    const local = LOCAL_HOSTS.includes(url.hostname) || url.hostname.endsWith(".localhost");
    if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) {
      throw new Error("Themi's address must start with https:// (http:// only for localhost).");
    }
    if (url.username || url.password || url.search || url.hash) {
      throw new Error("Just the address, please: no sign-in, ? or # parts.");
    }
    return (url.origin + url.pathname).replace(/\/+$/, "");
  }

  // The host permission to ask for, for that address.
  function originPattern(base) {
    return new URL(base).origin + "/*";
  }

  function createThemiApi({ base, token, fetchFn }) {
    async function call(path, init = {}) {
      const res = await fetchFn(base + path, {
        ...init,
        headers: { Authorization: "Bearer " + token, ...(init.body ? { "Content-Type": "application/json" } : {}) },
        credentials: "omit",
      });
      if (res.status === 401) throw new Revoked();
      if (res.status === 204) return null;
      const json = await res.json().catch(() => null);
      if (res.status >= 400) throw new Error("Themi said no: " + ((json && json.error) || res.status));
      return json;
    }
    return {
      async claim() {
        const json = await call("/api/safeway/claim", { method: "POST" });
        return json ? json.job : null;
      },
      postResults(jobId, body) {
        return call(`/api/safeway/jobs/${encodeURIComponent(jobId)}/results`, { method: "POST", body: JSON.stringify(body) });
      },
      async products() {
        const json = await call("/api/safeway/products");
        return (json && json.products) || [];
      },
      setProduct(name, product) {
        return call("/api/safeway/products", { method: "PUT", body: JSON.stringify({ name, product }) });
      },
    };
  }

  // Remembered products kept in Themi, with the same interface as fill.js's createMemory.
  // `ask` sends a message to whoever can reach Themi (the service worker).
  function createRemoteMemory(ask, itemKey) {
    let cache = null;
    async function all() {
      if (!cache) {
        const res = await ask({ type: "themi-products" });
        if (!res || !res.ok) throw new Error((res && res.detail) || "Couldn't reach Themi.");
        cache = {};
        for (const p of res.products) if (p.product) cache[itemKey(p.name)] = p.product;
      }
      return cache;
    }
    return {
      all,
      async get(key) {
        return (await all())[key] || null;
      },
      async set(key, product, name) {
        const value = { id: product.id, name: product.name, size: product.size || "", price: product.price ?? null };
        (await all())[key] = value;
        await ask({ type: "themi-set-product", name: name || key, product: value });
      },
      async forget() {},
    };
  }

  // fill.js's result for a job, as Themi takes it: one line per item it got to.
  function toResults(result) {
    const lines = [];
    const product = (p) => (p ? { id: String(p.id), name: String(p.name || "").slice(0, 200), size: String(p.size || "").slice(0, 40), price: typeof p.price === "number" ? p.price : null } : null);
    for (const e of result.added || []) lines.push({ name: e.item, status: "added", qty: e.qty, product: product(e.product) });
    for (const e of result.outOfStock || []) lines.push({ name: e.item, status: "out_of_stock", qty: e.qty || 1, product: product(e.product) });
    for (const e of result.notFound || []) lines.push({ name: e.item, status: "not_found", qty: e.qty || 1, product: null });
    for (const e of result.failed || []) lines.push({ name: e.item, status: "failed", qty: e.qty || 1, product: null });
    return { items: lines, stopped: Boolean(result.stopped) };
  }

  const api = { normalizeAddress, originPattern, createThemiApi, createRemoteMemory, toResults, Revoked };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ThemiLink = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
