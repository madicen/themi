// Parsing the shopping list typed into the popup: one item per line, an optional
// quantity in front ("2 oat milk"). Loaded as a classic script in the extension and
// with require() in the tests.
(function (root) {
  const MAX_QTY = 20; // Safeway's usual maxPurchaseQty
  const MAX_ITEMS = 60;
  const MAX_NAME = 80;

  function itemKey(name) {
    return name.toLowerCase().replace(/\s+/g, " ").trim();
  }

  function parseLine(line) {
    let text = line.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").trim();
    let qty = 1;
    // "2 oat milk", "2x oat milk" or "oat milk x2"; "7up" and "1% milk" are names.
    let m = text.match(/^(\d{1,3})(?:\s*x)?\s+(.+)$/i);
    if (m) {
      qty = Number(m[1]);
      text = m[2];
    } else if ((m = text.match(/^(.+?)\s+x\s*(\d{1,3})$/i))) {
      text = m[1];
      qty = Number(m[2]);
    }
    text = text.replace(/\s+/g, " ").trim().slice(0, MAX_NAME);
    if (!text) return null;
    return { name: text, qty: Math.min(Math.max(qty, 1), MAX_QTY) };
  }

  // Returns [{ key, name, qty }]. Blank lines are skipped and repeated items are merged,
  // keeping the first spelling and adding the quantities.
  function parseList(text) {
    const byKey = new Map();
    for (const line of String(text || "").split(/\r?\n/)) {
      const item = parseLine(line);
      if (!item) continue;
      const key = itemKey(item.name);
      const seen = byKey.get(key);
      if (seen) seen.qty = Math.min(seen.qty + item.qty, MAX_QTY);
      else if (byKey.size < MAX_ITEMS) byKey.set(key, { key, name: item.name, qty: item.qty });
    }
    return [...byKey.values()];
  }

  const api = { parseList, itemKey, MAX_QTY, MAX_ITEMS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ThemiList = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
