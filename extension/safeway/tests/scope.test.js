// The extension's limits: safeway.com only, three endpoints, and nothing for checkout,
// payment, delivery slots or addresses.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { SEARCH_PATH, CART_ITEMS_PATH, CART_PATH, createClient } = require("../lib/safeway.js");
const { fillCart, createMemory } = require("../lib/fill.js");
const { parseList } = require("../lib/list.js");
const { fixture, fakeSafeway, fakeStorage, ctx, noSleep } = require("./fakes.js");

const ROOT = path.join(__dirname, "..");
const SOURCES = ["manifest.json", "page.js", "content.js", "popup.html", "popup.js", "lib/list.js", "lib/safeway.js", "lib/fill.js"];

test("the manifest asks for storage and safeway.com only", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ["storage"]);
  assert.deepEqual(manifest.host_permissions, ["https://www.safeway.com/*"]);
  assert.equal(manifest.optional_host_permissions, undefined);
  for (const cs of manifest.content_scripts) assert.deepEqual(cs.matches, ["https://www.safeway.com/*"]);
});

test("no code mentions checkout, payment, slots or addresses", () => {
  for (const file of SOURCES) {
    const text = fs.readFileSync(path.join(ROOT, file), "utf8").toLowerCase();
    for (const word of ["checkout", "payment", "/slot", "slotservice", "orderservice", "/address", "/orders"]) {
      const mentions = text.split("\n").filter((line) => line.includes(word) && !/^\s*(\/\/|<!--)|you check out|nothing here for checkout/.test(line));
      assert.deepEqual(mentions, [], `${file} mentions ${word}`);
    }
  }
});

test("a fill only calls search, the cart read and the cart add, and never lowers a quantity", async () => {
  const site = fakeSafeway({ searches: { eggs: fixture("search-eggs.json") }, cart: { "960304348": { qty: 5 } } });
  const client = createClient({ ctx: ctx(), fetchFn: site.fetchFn, sleep: noSleep });
  await fillCart({ items: parseList("eggs\n2 oat milk\nqzxjvwk"), client, memory: createMemory(fakeStorage()) });
  for (const r of site.requests) {
    const allowed = (r.method === "GET" && (r.path === SEARCH_PATH || r.path.startsWith(CART_PATH))) || (r.method === "POST" && r.path === CART_ITEMS_PATH);
    assert.ok(allowed, `${r.method} ${r.path}`);
    if (r.method === "POST") assert.ok(r.body.cartItemsList.every((i) => i.qty >= 1));
  }
  assert.equal(site.lines.get("960304348").qty, 6);
});
