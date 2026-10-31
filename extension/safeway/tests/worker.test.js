const test = require("node:test");
const assert = require("node:assert/strict");
const { createWorker, jobItems } = require("../lib/worker.js");
const { itemKey } = require("../lib/list.js");
const { createClient } = require("../lib/safeway.js");
const { fillCart, createMemory } = require("../lib/fill.js");
const { fixture, fakeSafeway, fakeStorage, ctx, noSleep } = require("./fakes.js");

const PAIRED = { themiUrl: "https://themi.test", themiToken: "swh_" + "a".repeat(30), themiStatus: "connected" };
const JOB = { id: 7, items: [{ name: "eggs", qty: 2, search: "eggs", product: null }] };

function setup({ settings = PAIRED, tab = { id: 3 }, claim = [200, { job: JOB }], tabTakes = true } = {}) {
  const storage = fakeStorage(settings);
  const posted = [];
  const sentToTab = [];
  const polling = [];
  let claims = 0;
  const fetchFn = async (url, init = {}) => {
    const path = new URL(url).pathname;
    if (path === "/api/safeway/claim") {
      claims++;
      return { status: claim[0], json: async () => claim[1] };
    }
    posted.push({ path, body: JSON.parse(init.body) });
    return { status: 200, json: async () => ({ ok: true }) };
  };
  const worker = createWorker({
    storage: { get: async (k) => { const keys = Array.isArray(k) ? k : [k]; const out = {}; for (const key of keys) Object.assign(out, await storage.get(key)); return out; }, set: storage.set },
    findSafewayTab: async () => tab,
    sendToTab: async (id, msg) => (sentToTab.push({ id, msg }), tabTakes ? { ok: true } : null),
    fetchFn,
    setPolling: async (on) => polling.push(on),
  });
  return { worker, storage, posted, sentToTab, polling, claims: () => claims };
}

test("polls only while paired and a Safeway tab is open", async () => {
  const unpaired = setup({ settings: {} });
  assert.equal(await unpaired.worker.poll(), "unpaired");
  assert.equal(unpaired.claims(), 0);
  const noTab = setup({ tab: null });
  assert.equal(await noTab.worker.poll(), "no-tab");
  assert.deepEqual(noTab.polling, [false]);
  assert.equal(noTab.claims(), 0);
});

test("claims a job, hands it to the tab, and posts the results", async () => {
  const s = setup();
  assert.equal(await s.worker.poll(), "sent");
  assert.deepEqual(s.polling, [true]);
  assert.deepEqual(s.sentToTab, [{ id: 3, msg: { type: "job", job: JOB } }]);
  assert.equal(await s.worker.poll(), "busy", "one job at a time");
  const result = { added: [{ item: "eggs", key: "eggs", qty: 2, product: { id: "1", name: "Lucerne", size: "18 Count", price: 5.99 } }], notFound: [], outOfStock: [], failed: [], stopped: null };
  assert.equal(await s.worker.jobDone(7, result), "posted");
  assert.deepEqual(s.posted, [{ path: "/api/safeway/jobs/7/results", body: { items: [{ name: "eggs", status: "added", qty: 2, product: { id: "1", name: "Lucerne", size: "18 Count", price: 5.99 } }], stopped: false } }]);
  assert.equal(s.claims(), 1);
});

test("nothing to do is quiet; a tab that can't take the job frees the worker", async () => {
  assert.equal(await setup({ claim: [204, null] }).worker.poll(), "none");
  const s = setup({ tabTakes: false });
  assert.equal(await s.worker.poll(), "tab-refused");
  assert.equal(await s.worker.poll(), "tab-refused", "not stuck busy");
});

test("a 401 from Themi stops polling and says the connection was revoked", async () => {
  const s = setup({ claim: [401, { error: "not connected" }] });
  assert.equal(await s.worker.poll(), "revoked");
  assert.equal(s.storage.data.themiStatus, "revoked");
  assert.deepEqual(s.polling, [true, false]);
  assert.equal(await s.worker.poll(), "unpaired");
  assert.equal(s.claims(), 1);
  const res = await s.worker.products();
  assert.equal(res.ok, false);
});

test("job items: a remembered product skips the search; search words are what's searched", async () => {
  const items = jobItems(
    {
      items: [
        { name: "eggs", qty: 2, search: "eggs", product: { id: "970597593", name: "Just Egg - 16 Oz", size: "16 Oz" } },
        { name: "oat milk", qty: 1, search: "oatly oatmilk", product: null },
        { name: "", qty: 1 },
        { name: "rice", qty: 99, search: "", product: { id: "not digits" } },
        "junk",
      ],
    },
    itemKey,
  );
  assert.deepEqual(items.map((i) => [i.name, i.qty, i.search, i.product && i.product.id]), [
    ["eggs", 2, "eggs", "970597593"],
    ["oat milk", 1, "oatly oatmilk", null],
    ["rice", 1, "rice", null],
  ]);

  const site = fakeSafeway({ searches: { "oatly oatmilk": fixture("search-eggs.json") } });
  const client = createClient({ ctx: ctx(), fetchFn: site.fetchFn, sleep: noSleep });
  const result = await fillCart({ items: items.slice(0, 2), client, memory: createMemory(fakeStorage()) });
  const searched = site.requests.filter((r) => r.path.includes("search")).map((r) => r.params.q);
  assert.deepEqual(searched, ["oatly oatmilk"]);
  assert.equal(site.lines.get("970597593").qty, 2);
  assert.equal(site.lines.get("960304348").qty, 1);
  assert.equal(result.added.length, 2);
});
