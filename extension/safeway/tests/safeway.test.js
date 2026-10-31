const test = require("node:test");
const assert = require("node:assert/strict");
const { createClient, parseSearch, cartItems, requestId, SignedOut, SEARCH_PATH, CART_ITEMS_PATH, CART_PATH } = require("../lib/safeway.js");
const { fixture, fakeSafeway, ctx, noSleep } = require("./fakes.js");

test("search results: product ID, name, size, price and stock", () => {
  const found = parseSearch(fixture("search-eggs.json"));
  assert.equal(found.status, "ok");
  assert.equal(found.products.length, 4);
  assert.deepEqual(found.products[0], {
    id: "960304348",
    name: "Lucerne Farms Eggs Cage Free Large - 18 Count",
    size: "18 Count",
    price: 5.99,
    inStock: true,
  });
  assert.equal(found.products[3].inStock, false, "inventoryAvailable \"0\" is out of stock");
});

test("a search with no real match is not found", () => {
  assert.deepEqual(parseSearch(fixture("search-no-match.json")), { status: "no_match", products: [] });
});

test("a refused search is an error, not an empty result", () => {
  const found = parseSearch(fixture("search-bad-request-id.json"));
  assert.equal(found.status, "error");
  assert.match(found.detail, /OSSR0033-R/);
});

test("sponsored results are skipped", () => {
  const json = fixture("search-eggs.json");
  json.primaryProducts.response.docs[0].featured = true;
  assert.equal(parseSearch(json).products[0].id, "960273951");
});

test("cart responses: the add and the read", () => {
  const fromAdd = cartItems(fixture("cart-add-response.json"));
  const fromRead = cartItems(fixture("cart-get-response.json"));
  for (const items of [fromAdd, fromRead]) {
    const line = items.get("970597593");
    assert.equal(line.qty, 1);
    assert.equal(line.inStock, true);
    assert.equal(line.product.name, "Just Egg Plant-Based Egg - 16 Oz");
  }
});

test("request IDs look like the site's own", () => {
  assert.equal(requestId(1761900000000, () => 0), "1001761900000000100");
  assert.match(requestId(Date.now(), Math.random), /^\d{3}\d{13}\d{3}$/);
});

test("search sends the page's store and key, no sign-in token, and skips sponsored", async () => {
  const site = fakeSafeway({ searches: { eggs: fixture("search-eggs.json") } });
  const client = createClient({ ctx: ctx(), fetchFn: site.fetchFn, sleep: noSleep, now: () => 1761900000000, random: () => 0 });
  const found = await client.search("eggs");
  assert.equal(found.status, "ok");
  const [req] = site.requests;
  assert.equal(req.path, SEARCH_PATH);
  assert.equal(req.params.storeid, "1196");
  assert.equal(req.params.featured, "false");
  assert.equal(req.params["request-id"], "1001761900000000100");
  assert.equal(req.headers["Ocp-Apim-Subscription-Key"], "search-key");
  assert.equal(req.headers.Authorization, undefined);
});

test("setting a quantity posts the product ID with the cart's parameters", async () => {
  const site = fakeSafeway();
  const client = createClient({ ctx: ctx(), fetchFn: site.fetchFn, sleep: noSleep });
  const res = await client.setQuantity("970597593", 2);
  assert.equal(res.ok, true);
  const [req] = site.requests;
  assert.equal(req.method, "POST");
  assert.equal(req.path, CART_ITEMS_PATH);
  assert.deepEqual(req.params, { storeId: "1196", serviceType: "Delivery", zipCode: "00000", cartCategoryList: "1P" });
  assert.equal(req.headers.Authorization, "Bearer test-token");
  assert.deepEqual(req.body, { cartItemsList: [{ itemId: "970597593", qty: 2, comments: "", isSnsSub: false }], cartCategory: "abs" });
});

test("pickup uses Safeway's DUG service type", async () => {
  const site = fakeSafeway();
  const client = createClient({ ctx: { ...ctx(), channel: "pickup" }, fetchFn: site.fetchFn, sleep: noSleep });
  await client.readCart();
  assert.equal(site.requests[0].params.serviceType, "DUG");
  assert.equal(site.requests[0].path, CART_PATH + "100000001");
});

test("a new cart (no cart ID yet) reads as empty without a request", async () => {
  const site = fakeSafeway();
  const client = createClient({ ctx: { ...ctx(), cartId: "" }, fetchFn: site.fetchFn, sleep: noSleep });
  assert.equal((await client.readCart()).size, 0);
  assert.equal(site.requests.length, 0);
});

test("signed out, a bad token, no token or a bot check all stop with SignedOut", async () => {
  const cases = [
    { site: fakeSafeway({ signedOut: true }), ctx: ctx() },
    { site: { fetchFn: async () => ({ status: 403, text: async () => JSON.stringify(fixture("cart-bad-token-403.json")) }) }, ctx: ctx() },
    { site: fakeSafeway(), ctx: { ...ctx(), token: "" } },
    { site: fakeSafeway({ botCheck: true }), ctx: ctx() },
    { site: { fetchFn: async () => { throw new TypeError("Failed to fetch"); } }, ctx: ctx() },
  ];
  for (const c of cases) {
    const client = createClient({ ctx: c.ctx, fetchFn: c.site.fetchFn, sleep: noSleep });
    await assert.rejects(client.setQuantity("970597593", 1), SignedOut);
  }
});

test("requests are paced: a pause before every request after the first", async () => {
  const site = fakeSafeway();
  const pauses = [];
  const client = createClient({ ctx: ctx(), fetchFn: site.fetchFn, sleep: async (ms) => pauses.push(ms), random: () => 0.5 });
  await client.search("eggs");
  await client.readCart();
  await client.setQuantity("970597593", 1);
  assert.deepEqual(pauses, [1500, 1500]);
});
