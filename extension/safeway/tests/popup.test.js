// SW1: the popup lists Themi's grocery list, ticks what isn't in the cart yet, and only
// shows a recent fill (the old one stayed up for weeks).
const test = require("node:test");
const assert = require("node:assert/strict");
const { freshRun, recentFill, ago, addExtras, rows, toggle, toFill, notice, counts, FRESH_FOR_MS } = require("../lib/popup.js");
const { jobItems } = require("../lib/worker.js");
const { itemKey } = require("../lib/list.js");

const NOW = 1_800_000_000_000;
const EGGS = { id: "960304348", name: "Lucerne Eggs - 18 Count", size: "18 Count" };
const THEMI = [
  { name: "eggs", qty: 1, search: "eggs", product: EGGS, from: "groceries" },
  { name: "oat milk", qty: 2, search: "oatly oat milk", product: null, from: "groceries" },
  { name: "batteries", qty: 1, search: "batteries", product: null, from: "Things to Buy" },
];
const done = (added, at = NOW - 60_000) => ({ state: "done", at, result: { added: added.map((item) => ({ item, qty: 1, product: { id: "1", name: item, price: 2.5 } })), notFound: [], outOfStock: [], failed: [] } });

test("a fill is shown while it runs and for 12 hours after, not once dismissed", () => {
  assert.equal(freshRun({ state: "running", done: 1, total: 3, at: NOW - 5000 }, NOW).state, "running");
  assert.equal(freshRun({ state: "running", done: 1, total: 3, at: NOW - 10 * 60_000 }, NOW), null); // tab closed mid-fill
  assert.equal(freshRun({ state: "running", done: 1, total: 3 }, NOW), null); // from before SW1
  assert.ok(freshRun(done([]), NOW));
  assert.equal(freshRun(done([], NOW - FRESH_FOR_MS - 1), NOW), null); // the cart from ages ago
  assert.equal(freshRun({ ...done([]), dismissed: true }, NOW), null);
  assert.equal(freshRun({ state: "done", result: {} }, NOW), null); // from before SW1: no time
  assert.equal(freshRun(null, NOW), null);
  // dismissed, what it added still counts as in the cart for those 12 hours
  assert.ok(recentFill({ ...done(["eggs"]), dismissed: true }, NOW));
  assert.equal(recentFill(done(["eggs"], NOW - FRESH_FOR_MS - 1), NOW), null);
});

test("how long ago, in words", () => {
  assert.equal(ago(NOW - 10_000, NOW), "just now");
  assert.equal(ago(NOW - 60_000, NOW), "a minute ago");
  assert.equal(ago(NOW - 25 * 60_000, NOW), "25 minutes ago");
  assert.equal(ago(NOW - 61 * 60_000, NOW), "an hour ago");
  assert.equal(ago(NOW - 5 * 3600_000, NOW), "5 hours ago");
});

test("Themi's items come first and are ticked; typed extras follow, merged by name", () => {
  const extras = addExtras(addExtras([], "bread\n2 Eggs"), "2 bread");
  assert.deepEqual(extras, [{ name: "bread", qty: 3 }, { name: "Eggs", qty: 2 }]);
  const list = rows({ themiItems: THEMI, extras });
  assert.deepEqual(list.map((r) => [r.name, r.qty, r.checked, r.extra]), [
    ["eggs", 1, true, false],
    ["oat milk", 2, true, false],
    ["batteries", 1, true, false],
    ["bread", 3, true, true], // "Eggs" is on Themi's list already
  ]);
  assert.equal(list[2].from, "Things to Buy");
});

test("what the last fill added isn't ticked again, unless someone ticks it", () => {
  const run = done(["eggs"]);
  let list = rows({ themiItems: THEMI, run });
  assert.deepEqual(list.map((r) => [r.name, r.inCart, r.checked]), [["eggs", true, false], ["oat milk", false, true], ["batteries", false, true]]);
  const unchecked = toggle(toggle([], list[0], true), list[1], false);
  list = rows({ themiItems: THEMI, run, unchecked });
  assert.deepEqual(list.map((r) => r.checked), [true, false, true]);
  assert.deepEqual(toggle(unchecked, list[0], false), ["oat milk"]); // back to its default
});

test("with a cart waiting for the helper, Themi's items start unticked; extras don't", () => {
  const list = rows({ themiItems: THEMI, extras: [{ name: "bread", qty: 1 }], waiting: true });
  assert.deepEqual(list.map((r) => r.checked), [false, false, false, true]);
});

test("the ticked rows go to the tab as a job's items, which the tab accepts", () => {
  const list = rows({ themiItems: THEMI, extras: [{ name: "bread", qty: 1 }], unchecked: ["batteries"] });
  const items = toFill(list);
  assert.deepEqual(items.map((i) => i.name), ["eggs", "oat milk", "bread"]);
  const checked = jobItems({ items }, itemKey);
  assert.deepEqual(checked.map((i) => [i.name, i.qty, i.search, i.product && i.product.id]), [
    ["eggs", 1, "eggs", "960304348"], // remembered: no search
    ["oat milk", 2, "oatly oat milk", undefined],
    ["bread", 1, "bread", undefined],
  ].map(([n, q, s, p]) => [n, q, s, p === undefined ? null : p]));
});

test("one notice, the most pressing", () => {
  assert.equal(notice({ tab: "ready" }), null);
  assert.equal(notice({ tab: "none" }).action, "open");
  assert.equal(notice({ tab: "reload" }).action, "reload");
  assert.equal(notice({ tab: "sign-in" }).action, "show");
  assert.equal(notice({ tab: "ready", themiError: true }).action, "retry");
  assert.equal(notice({ tab: "none", themiStatus: "revoked" }).action, "options");
});

test("a fill's counts and its rough total", () => {
  assert.deepEqual(counts(done(["eggs", "milk"]).result), { added: 2, total: 2, about: 5, allPriced: true });
  assert.deepEqual(counts({ added: [{ item: "x", qty: 1, product: { price: null } }], notFound: [{ item: "y" }] }), { added: 1, total: 2, about: null, allPriced: false });
});
