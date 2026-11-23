// The popup's logic (SW1), apart from the DOM so the tests can drive it: the rows it lists
// (Themi's grocery list plus anything typed in), which are ticked, whether the last fill is
// still worth showing, and the one notice at the top.
(function (root) {
  const List = typeof module !== "undefined" && module.exports ? require("./list.js") : root.ThemiList;
  const FRESH_FOR_MS = 12 * 60 * 60 * 1000; // a fill older than this is yesterday's shop
  const MAX_EXTRAS = 30;
  const STALLED_AFTER_MS = 3 * 60 * 1000; // no progress this long: the tab closed mid-fill

  // The last fill, while it's worth showing: running, or done in the last 12 hours and not
  // dismissed with Done. Older ones were the cart from ages ago.
  function freshRun(run, now) {
    if (run && run.state === "running") return running(run, now) ? run : null;
    const recent = recentFill(run, now);
    return recent && !recent.dismissed ? recent : null;
  }

  // A fill still going: it updates `at` with each item, so one that stopped moving (its tab
  // was closed or reloaded partway) doesn't hold the button forever.
  function running(run, now) {
    return Boolean(run && run.state === "running" && typeof run.at === "number" && now - run.at < STALLED_AFTER_MS);
  }

  // The last finished fill if it was in the last 12 hours, dismissed or not: what it added
  // is still in the cart, so it isn't ticked to go in twice.
  function recentFill(run, now) {
    if (!run || run.state !== "done" || typeof run.at !== "number") return null;
    return now - run.at < FRESH_FOR_MS ? run : null;
  }

  function ago(at, now) {
    const minutes = Math.floor((now - at) / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return minutes === 1 ? "a minute ago" : `${minutes} minutes ago`;
    const hours = Math.floor(minutes / 60);
    return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  }

  // Item keys the fresh fill put in the cart, so they aren't ticked to go in twice.
  function inCart(run) {
    const keys = new Set();
    if (run && run.state === "done" && run.result) {
      for (const e of run.result.added || []) keys.add(List.itemKey(e.item));
    }
    return keys;
  }

  // Lines typed or pasted into the add box -> extras to keep, merged into what's there.
  function addExtras(extras, text) {
    const out = (extras || []).map((e) => ({ ...e }));
    for (const item of List.parseList(text)) {
      const seen = out.find((e) => List.itemKey(e.name) === item.key);
      if (seen) seen.qty = Math.min(seen.qty + item.qty, List.MAX_QTY);
      else if (out.length < MAX_EXTRAS) out.push({ name: item.name, qty: item.qty });
    }
    return out;
  }

  // The rows: Themi's items first (each like a job's item, plus `from`), then the extras not
  // already on Themi's list. A row is ticked unless someone unticked it, the last fill put it
  // in the cart, or Themi has a cart waiting for the helper (it'd go in twice).
  // -> [{ key, name, qty, search, product, from, extra, inCart, defaultOn, checked }]
  function rows({ themiItems = [], extras = [], unchecked = [], run = null, waiting = false }) {
    const off = new Set(unchecked);
    const added = inCart(run);
    const out = [];
    const keys = new Set();
    const push = (row) => {
      keys.add(row.key);
      const isInCart = added.has(row.key);
      const defaultOn = !isInCart && !(waiting && !row.extra);
      out.push({ ...row, inCart: isInCart, defaultOn, checked: off.has(row.key) ? false : off.has("+" + row.key) ? true : defaultOn });
    };
    for (const item of themiItems) {
      const key = List.itemKey(item.name);
      if (!key || keys.has(key)) continue;
      push({ key, name: item.name, qty: item.qty, search: item.search || item.name, product: item.product || null, from: item.from || "groceries", extra: false });
    }
    for (const e of extras) {
      const key = List.itemKey(e.name);
      if (!key || keys.has(key)) continue;
      push({ key, name: e.name, qty: e.qty, search: e.name, product: null, from: null, extra: true });
    }
    return out;
  }

  // A tick toggled: `unchecked` keeps "key" for a row turned off and "+key" for a row turned
  // on against its default (in the cart already, or a cart waiting).
  function toggle(unchecked, row, on) {
    const out = (unchecked || []).filter((k) => k !== row.key && k !== "+" + row.key);
    if (on && !row.defaultOn) out.push("+" + row.key);
    if (!on && row.defaultOn) out.push(row.key);
    return out;
  }

  // What to send the tab: the ticked rows as a job's items (the tab checks them again).
  function toFill(list) {
    return list
      .filter((r) => r.checked)
      .map((r) => ({ name: r.name, qty: r.qty, search: r.search, product: r.product ? { id: r.product.id, name: r.product.name, size: r.product.size || "" } : null }));
  }

  // The notice at the top, most pressing first. tab: "ready" | "none" | "reload" | "sign-in".
  // -> { kind, text, action } or null; action is what its button does.
  function notice({ tab, themiStatus, themiError }) {
    if (themiStatus === "revoked") return { kind: "warn", text: "Themi disconnected this helper. Make a new token on Themi's Safeway page.", action: "options" };
    if (tab === "none") return { kind: "info", text: "Open Safeway and sign in to fill the cart.", action: "open" };
    if (tab === "reload") return { kind: "warn", text: "The Safeway tab was open before the helper was updated. Reload it so the helper can use it.", action: "reload" };
    if (tab === "sign-in") return { kind: "warn", text: "Sign in on the Safeway tab, then come back.", action: "show" };
    if (themiError) return { kind: "warn", text: "Couldn't reach Themi for the grocery list.", action: "retry" };
    return null;
  }

  function counts(result) {
    const r = result || {};
    const added = (r.added || []).length;
    const total = added + (r.notFound || []).length + (r.outOfStock || []).length + (r.failed || []).length;
    const prices = (r.added || []).map((e) => (e.product && typeof e.product.price === "number" ? e.product.price * (e.qty || 1) : null));
    const priced = prices.filter((p) => p !== null);
    return { added, total, about: priced.length ? priced.reduce((a, b) => a + b, 0) : null, allPriced: priced.length === prices.length };
  }

  const api = { freshRun, running, recentFill, ago, addExtras, rows, toggle, toFill, notice, counts, FRESH_FOR_MS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ThemiPopup = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
