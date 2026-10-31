// The only three calls the extension makes to safeway.com: product search, reading the
// cart, and setting one product's quantity in it. See ../NOTES.md for how they were found.
// There is deliberately nothing here for checkout, payment, delivery slots or addresses.
(function (root) {
  const ORIGIN = "https://www.safeway.com";
  const SEARCH_PATH = "/abs/pub/xapi/pgmsearch/v1/search/products";
  const CART_ITEMS_PATH = "/abs/pub/erums/cartservice/api/v2/cart/items";
  const CART_PATH = "/abs/pub/erums/cartservice/api/v2/cart/";
  const SIGN_IN_MESSAGE = "Sign in to Safeway, then try again.";

  class SignedOut extends Error {
    constructor(detail) {
      super(SIGN_IN_MESSAGE);
      this.name = "SignedOut";
      this.detail = detail;
    }
  }

  // The site's own format: 3 random digits, the time in ms, 3 random digits. The search
  // service refuses other shapes (OSSR0033-R).
  function requestId(now, random) {
    const three = () => String(100 + Math.floor(random() * 900));
    return three() + String(now) + three();
  }

  function sizeOf(doc) {
    const name = String(doc.name || "");
    const dash = name.lastIndexOf(" - ");
    if (dash > 0 && /\d/.test(name.slice(dash + 3))) return name.slice(dash + 3).trim();
    const qty = doc.dispItemSizeQty || doc.itemSizeQty;
    const unit = doc.dispUnitOfMeasure || doc.unitOfMeasure;
    return qty && unit ? `${qty} ${unit}`.toLowerCase() : "";
  }

  function productOf(doc) {
    return {
      id: String(doc.pid || doc.id || doc.itemId),
      name: String(doc.name || "").slice(0, 200),
      size: sizeOf(doc).slice(0, 40),
      price: typeof doc.price === "number" ? doc.price : null,
      inStock: doc.inventoryAvailable !== undefined ? String(doc.inventoryAvailable) === "1" : !doc.isOOS,
    };
  }

  // -> { status: "ok" | "no_match" | "error", products: [...] }
  function parseSearch(json) {
    const pp = json && json.primaryProducts;
    const resp = pp && pp.response;
    if (!resp || !Array.isArray(resp.docs)) {
      return { status: "error", products: [], detail: pp ? String(pp.appMsg || pp.appCode || "") : "no products" };
    }
    if (resp.isExactMatch === false || resp.docs.length === 0) return { status: "no_match", products: [] };
    const products = resp.docs
      .filter((d) => d.featured !== true && (d.status === undefined || d.status === "active"))
      .map(productOf)
      .filter((p) => /^\d+$/.test(p.id));
    return products.length ? { status: "ok", products } : { status: "no_match", products: [] };
  }

  // Cart responses: the add returns { carts: [cart] }, the read returns the cart itself.
  function cartItems(json) {
    const carts = json && Array.isArray(json.carts) ? json.carts : json && json.cartItemsList ? [json] : [];
    const items = new Map();
    for (const cart of carts) {
      for (const item of cart.cartItemsList || []) {
        items.set(String(item.itemId), { qty: Number(item.qty) || 0, inStock: !item.isOOS && item.isAvailable !== false, product: productOf(item) });
      }
    }
    return items;
  }

  function serviceType(channel) {
    return channel === "pickup" ? "DUG" : "Delivery";
  }

  // ctx comes from page.js (the page's own globals): storeId, banner, zipCode, channel,
  // token, searchKey, cartKey, cartId. fetchFn and sleep are injected so tests need no network.
  function createClient({ ctx, fetchFn, sleep, now = () => Date.now(), random = Math.random, pauseMs = 1200 }) {
    let calls = 0;

    async function call(url, init) {
      if (calls++ > 0) await sleep(pauseMs + Math.floor(random() * 600));
      let res;
      try {
        res = await fetchFn(url, { credentials: "include", ...init });
      } catch (e) {
        // Akamai's bot check drops the connection rather than answering.
        throw new SignedOut("network: " + String(e && e.message));
      }
      if (res.status === 401 || res.status === 403) throw new SignedOut("http " + res.status);
      const text = await res.text();
      let json;
      try {
        json = JSON.parse(text);
      } catch {
        // An HTML page instead of JSON is a sign-in redirect or a bot check.
        throw new SignedOut("not json, http " + res.status);
      }
      return { status: res.status, json };
    }

    function cartHeaders() {
      if (!ctx.token) throw new SignedOut("no token");
      return { "Content-Type": "application/json", "Ocp-Apim-Subscription-Key": ctx.cartKey, Authorization: "Bearer " + ctx.token };
    }

    function cartQuery(path) {
      const u = new URL(path, ORIGIN);
      u.searchParams.set("storeId", ctx.storeId);
      u.searchParams.set("serviceType", serviceType(ctx.channel));
      u.searchParams.set("zipCode", ctx.zipCode || "");
      u.searchParams.set("cartCategoryList", "1P");
      return u.href;
    }

    async function search(q, rows = 12) {
      const u = new URL(SEARCH_PATH, ORIGIN);
      const params = {
        "request-id": requestId(now(), random),
        url: ORIGIN,
        pageurl: ORIGIN,
        pagename: "search",
        rows: String(rows),
        start: "0",
        "search-type": "keyword",
        storeid: ctx.storeId,
        featured: "false",
        q,
        sort: "",
        dvid: "web-4.1search",
        channel: ctx.channel || "delivery",
        banner: ctx.banner || "safeway",
        pp: "true",
      };
      for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
      const { status, json } = await call(u.href, { headers: { "Ocp-Apim-Subscription-Key": ctx.searchKey, Accept: "application/json" } });
      if (status >= 400) return { status: "error", products: [], detail: "http " + status };
      return parseSearch(json);
    }

    // -> Map(product id -> { qty, inStock, product }). A cart that doesn't exist yet is empty.
    async function readCart() {
      if (!ctx.cartId) return new Map();
      const { status, json } = await call(cartQuery(CART_PATH + encodeURIComponent(ctx.cartId)), { headers: cartHeaders() });
      if (status >= 400) throw new Error("Couldn't read the Safeway cart (" + status + ").");
      return cartItems(json);
    }

    // Safeway's add sets the quantity; callers pass the new total, never less than what's there.
    async function setQuantity(productId, qty) {
      const body = { cartItemsList: [{ itemId: String(productId), qty, comments: "", isSnsSub: false }], cartCategory: "abs" };
      const { status, json } = await call(cartQuery(CART_ITEMS_PATH), { method: "POST", headers: cartHeaders(), body: JSON.stringify(body) });
      if (status >= 400) {
        return { ok: false, detail: String((json && (json.developerMessage || json.errorMessage)) || "http " + status) };
      }
      const carts = (json && json.carts) || [];
      if (carts[0] && carts[0].cartId && !ctx.cartId) ctx.cartId = String(carts[0].cartId);
      return { ok: true, cart: cartItems(json) };
    }

    return { search, readCart, setQuantity };
  }

  const api = { createClient, parseSearch, cartItems, requestId, SignedOut, SIGN_IN_MESSAGE, ORIGIN, SEARCH_PATH, CART_ITEMS_PATH, CART_PATH };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ThemiSafeway = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
