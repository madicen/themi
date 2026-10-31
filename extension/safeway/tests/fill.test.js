const test = require("node:test");
const assert = require("node:assert/strict");
const { createClient, SIGN_IN_MESSAGE, SEARCH_PATH } = require("../lib/safeway.js");
const { fillCart, alternatives, choose, createMemory, CHOICES_KEY } = require("../lib/fill.js");
const { parseList } = require("../lib/list.js");
const { fixture, fakeSafeway, fakeStorage, ctx, noSleep } = require("./fakes.js");

const EGGS = "960304348";
const OUT_OF_STOCK_EGGS = "960454622";

function setup({ site = {}, choices = {} } = {}) {
  const fake = fakeSafeway({ searches: { eggs: fixture("search-eggs.json") }, ...site });
  const storage = fakeStorage({ [CHOICES_KEY]: choices });
  const client = createClient({ ctx: ctx(), fetchFn: fake.fetchFn, sleep: noSleep });
  return { fake, storage, client, memory: createMemory(storage) };
}

test("searches each item, adds the top result and remembers it", async () => {
  const { fake, storage, client, memory } = setup();
  const result = await fillCart({ items: parseList("2 eggs"), client, memory });
  assert.equal(result.stopped, null);
  assert.equal(result.added.length, 1);
  assert.equal(result.added[0].product.id, EGGS);
  assert.equal(result.added[0].qty, 2);
  assert.equal(fake.lines.get(EGGS).qty, 2);
  assert.equal(storage.data[CHOICES_KEY].eggs.id, EGGS);
});

test("a remembered choice is added by ID without searching", async () => {
  const { fake, client, memory } = setup({ choices: { "oat milk": { id: "960451820", name: "Oatly Oatmilk - 64 Oz", size: "64 Oz", price: 5.99 } } });
  const result = await fillCart({ items: parseList("oat milk"), client, memory });
  assert.equal(result.added[0].product.id, "960451820");
  assert.equal(result.added[0].remembered, true);
  assert.equal(fake.requests.filter((r) => r.path === SEARCH_PATH).length, 0);
});

test("adds on top of what's already in the cart, never lowering it", async () => {
  const { fake, client, memory } = setup({ site: { cart: { [EGGS]: { qty: 3 } } } });
  await fillCart({ items: parseList("eggs"), client, memory });
  assert.equal(fake.lines.get(EGGS).qty, 4);
  const posted = fake.requests.filter((r) => r.method === "POST").map((r) => r.body.cartItemsList[0].qty);
  assert.deepEqual(posted, [4]);
});

test("items with no real match are listed as not found", async () => {
  const { fake, client, memory } = setup();
  const result = await fillCart({ items: parseList("qzxjvwk"), client, memory });
  assert.deepEqual(result.notFound, [{ item: "qzxjvwk" }]);
  assert.equal(fake.requests.filter((r) => r.method === "POST").length, 0);
});

test("an out-of-stock top result isn't added and is listed", async () => {
  const json = fixture("search-eggs.json");
  json.primaryProducts.response.docs = [json.primaryProducts.response.docs[3]];
  const { fake, client, memory, storage } = setup({ site: { searches: { eggs: json } } });
  const result = await fillCart({ items: parseList("eggs"), client, memory });
  assert.equal(result.outOfStock[0].product.id, OUT_OF_STOCK_EGGS);
  assert.equal(result.added.length, 0);
  assert.equal(fake.requests.filter((r) => r.method === "POST").length, 0);
  assert.equal(storage.data[CHOICES_KEY].eggs, undefined);
});

test("a remembered product the cart says is out of stock is listed as out of stock", async () => {
  const { client, memory } = setup({ site: { outOfStock: [EGGS] }, choices: { eggs: { id: EGGS, name: "Lucerne eggs", size: "18 Count", price: 5.99 } } });
  const result = await fillCart({ items: parseList("eggs"), client, memory });
  assert.equal(result.added.length, 0);
  assert.equal(result.outOfStock[0].product.id, EGGS);
});

test("stops on the first signed-out response and says to sign in", async () => {
  const { fake, client, memory } = setup({ site: { signedOut: true } });
  const result = await fillCart({ items: parseList("eggs\nbananas\nrice"), client, memory });
  assert.equal(result.stopped, SIGN_IN_MESSAGE);
  assert.equal(fake.requests.length, 1, "nothing after the 401");
});

test("stops on a bot check partway through and keeps what was added", async () => {
  const { fake, memory } = setup();
  const realFetch = fake.fetchFn;
  let calls = 0;
  const flaky = createClient({
    ctx: ctx(),
    fetchFn: async (url, init) => (++calls > 3 ? { status: 200, text: async () => "<html>Access Denied</html>" } : realFetch(url, init)),
    sleep: noSleep,
  });
  const result = await fillCart({ items: parseList("eggs\nbananas"), client: flaky, memory });
  assert.equal(result.added.length, 1);
  assert.equal(result.stopped, SIGN_IN_MESSAGE);
});

test("progress is reported per item", async () => {
  const { client, memory } = setup();
  const seen = [];
  await fillCart({ items: parseList("eggs\nqzxjvwk"), client, memory, onProgress: (p) => seen.push(p) });
  assert.deepEqual(seen, [
    { done: 0, total: 2, item: "eggs" },
    { done: 1, total: 2, item: "qzxjvwk" },
    { done: 2, total: 2, item: null },
  ]);
});

test("change: other results, then the chosen one is remembered and added", async () => {
  const { fake, client, memory, storage } = setup({ site: { cart: { [EGGS]: { qty: 1 } } }, choices: { eggs: { id: EGGS, name: "Lucerne", size: "", price: 5.99 } } });
  const others = await alternatives({ item: "eggs", client, exclude: EGGS });
  assert.ok(others.every((p) => p.id !== EGGS));
  const picked = others[0];
  const res = await choose({ key: "eggs", qty: 1, product: picked, client, memory });
  assert.equal(res.ok, true);
  assert.equal(storage.data[CHOICES_KEY].eggs.id, picked.id);
  assert.equal(fake.lines.get(picked.id).qty, 1);
  assert.equal(fake.lines.get(EGGS).qty, 1, "the old product is left alone");
});

test("the remembered choices can be forgotten", async () => {
  const { memory } = setup({ choices: { eggs: { id: EGGS } } });
  await memory.forget("eggs");
  assert.equal(await memory.get("eggs"), null);
});
