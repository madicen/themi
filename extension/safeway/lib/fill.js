// Filling the cart from a parsed list, one request at a time. Remembered choices
// (item -> product) are used before searching. The cart is only ever added to.
(function (root) {
  const ThemiSafeway = typeof module !== "undefined" && module.exports ? require("./safeway.js") : root.ThemiSafeway;
  const CHOICES_KEY = "choices";

  // A remembered product per item key, kept in chrome.storage.local (or a fake in tests).
  function createMemory(storage) {
    async function all() {
      const got = await storage.get(CHOICES_KEY);
      return (got && got[CHOICES_KEY]) || {};
    }
    return {
      all,
      async get(key) {
        return (await all())[key] || null;
      },
      async set(key, product) {
        const choices = await all();
        choices[key] = { id: product.id, name: product.name, size: product.size, price: product.price };
        await storage.set({ [CHOICES_KEY]: choices });
      },
      async forget(key) {
        const choices = await all();
        delete choices[key];
        await storage.set({ [CHOICES_KEY]: choices });
      },
    };
  }

  // Adds qty of product on top of whatever is already in the cart.
  async function addOnTop(client, cart, product, qty) {
    const have = cart.has(product.id) ? cart.get(product.id).qty : 0;
    const res = await client.setQuantity(product.id, have + qty);
    if (!res.ok) return { ok: false, detail: res.detail };
    for (const [id, line] of res.cart) cart.set(id, line);
    const line = cart.get(product.id);
    if (!line) return { ok: false, detail: "Safeway didn't add it." };
    if (!line.inStock) return { ok: false, outOfStock: true, product: { ...product, ...line.product, id: product.id } };
    return { ok: true, product: { ...product, name: line.product.name || product.name, price: line.product.price ?? product.price } };
  }

  // items: [{ key, name, qty }] from parseList.
  // -> { added, notFound, outOfStock, failed, stopped } where stopped is a message or null.
  async function fillCart({ items, client, memory, onProgress = () => {} }) {
    const result = { added: [], notFound: [], outOfStock: [], failed: [], stopped: null };
    try {
      const cart = await client.readCart();
      for (const [i, item] of items.entries()) {
        onProgress({ done: i, total: items.length, item: item.name });
        let product = await memory.get(item.key);
        const remembered = Boolean(product);
        if (!product) {
          const found = await client.search(item.name);
          if (found.status === "error") {
            result.failed.push({ item: item.name, detail: found.detail });
            continue;
          }
          if (!found.products.length) {
            result.notFound.push({ item: item.name });
            continue;
          }
          product = found.products[0];
          if (!product.inStock) {
            result.outOfStock.push({ item: item.name, key: item.key, qty: item.qty, product });
            continue;
          }
        }
        const added = await addOnTop(client, cart, product, item.qty);
        if (added.ok) {
          if (!remembered) await memory.set(item.key, added.product);
          result.added.push({ item: item.name, key: item.key, qty: item.qty, product: added.product, remembered });
        } else if (added.outOfStock) {
          result.outOfStock.push({ item: item.name, key: item.key, qty: item.qty, product: added.product || product });
        } else {
          result.failed.push({ item: item.name, detail: added.detail });
        }
      }
      onProgress({ done: items.length, total: items.length, item: null });
    } catch (e) {
      if (e instanceof ThemiSafeway.SignedOut) result.stopped = ThemiSafeway.SIGN_IN_MESSAGE;
      else result.stopped = String((e && e.message) || e);
    }
    return result;
  }

  // "change": the other search results for an item, so a person can pick a different one.
  async function alternatives({ item, client, exclude }) {
    const found = await client.search(item);
    return found.products.filter((p) => p.id !== exclude);
  }

  // A person picked a different product: remember it and add it. The old one stays in the
  // cart (the extension never removes anything); the popup says so.
  async function choose({ key, qty, product, client, memory }) {
    try {
      const cart = await client.readCart();
      const added = await addOnTop(client, cart, product, qty);
      if (added.ok || added.outOfStock) await memory.set(key, product);
      return added.ok ? { ok: true, product: added.product } : { ok: false, outOfStock: Boolean(added.outOfStock), detail: added.detail };
    } catch (e) {
      if (e instanceof ThemiSafeway.SignedOut) return { ok: false, detail: ThemiSafeway.SIGN_IN_MESSAGE };
      throw e;
    }
  }

  const api = { fillCart, alternatives, choose, createMemory, CHOICES_KEY };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ThemiFill = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
