// A fake safeway.com for the tests: answers from the saved fixtures, keeps a cart, and
// records every request. No network.
const fs = require("node:fs");
const path = require("node:path");
const { SEARCH_PATH, CART_ITEMS_PATH, CART_PATH } = require("../lib/safeway.js");

function fixture(name) {
  return JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", name), "utf8"));
}

function response(status, body) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return { status, ok: status < 400, text: async () => text };
}

// searches: { query: fixture json }. Unknown queries get the no-match fixture.
function fakeSafeway({ searches = {}, cart = {}, outOfStock = [], signedOut = false, botCheck = false } = {}) {
  const requests = [];
  const lines = new Map(Object.entries(cart).map(([id, line]) => [id, { ...line }]));
  const template = fixture("cart-get-response.json");

  function cartJson() {
    return {
      ...template,
      cartItemsList: [...lines.entries()].map(([id, line]) => ({
        ...template.cartItemsList[0],
        itemId: Number(id),
        name: line.name || `Product ${id}`,
        qty: line.qty,
        isOOS: outOfStock.includes(id),
        isAvailable: !outOfStock.includes(id),
      })),
    };
  }

  async function fetchFn(url, init = {}) {
    const u = new URL(url);
    const method = init.method || "GET";
    requests.push({ method, path: u.pathname, params: Object.fromEntries(u.searchParams), headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : null });
    if (botCheck) return response(200, "<html><title>Access Denied</title></html>");
    if (u.pathname === SEARCH_PATH) {
      const q = u.searchParams.get("q");
      return response(200, searches[q] || fixture("search-no-match.json"));
    }
    if (signedOut) return response(401, fixture("cart-signed-out-401.json"));
    if (u.pathname === CART_ITEMS_PATH && method === "POST") {
      for (const item of JSON.parse(init.body).cartItemsList) {
        const id = String(item.itemId);
        lines.set(id, { ...(lines.get(id) || {}), qty: item.qty });
      }
      return response(200, { carts: [{ ...cartJson(), cartId: 100000001 }], errors: [] });
    }
    if (u.pathname.startsWith(CART_PATH) && method === "GET") return response(200, cartJson());
    return response(404, { status: 404, error: "Not Found" });
  }

  return { fetchFn, requests, lines };
}

function fakeStorage(initial = {}) {
  const data = JSON.parse(JSON.stringify(initial));
  return {
    data,
    async get(key) {
      return key in data ? { [key]: JSON.parse(JSON.stringify(data[key])) } : {};
    },
    async set(values) {
      Object.assign(data, JSON.parse(JSON.stringify(values)));
    },
  };
}

const ctx = () => ({
  storeId: "1196",
  banner: "safeway",
  zipCode: "00000",
  channel: "delivery",
  token: "test-token",
  searchKey: "search-key",
  cartKey: "cart-key",
  cartId: "100000001",
});

const noSleep = async () => {};

module.exports = { fixture, fakeSafeway, fakeStorage, ctx, noSleep };
