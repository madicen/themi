const test = require("node:test");
const assert = require("node:assert/strict");
const { normalizeAddress, originPattern, createThemiApi, createRemoteMemory, toResults, Revoked } = require("../lib/themi.js");
const { itemKey } = require("../lib/list.js");

test("Themi's address: https anywhere, http only on this computer", () => {
  assert.equal(normalizeAddress(" https://themi.example.com/ "), "https://themi.example.com");
  assert.equal(normalizeAddress("https://example.com/themi/"), "https://example.com/themi");
  assert.equal(normalizeAddress("http://localhost:8000"), "http://localhost:8000");
  assert.equal(normalizeAddress("http://127.0.0.1:8000/"), "http://127.0.0.1:8000");
  for (const bad of ["", "themi.example.com", "http://themi.example.com", "ftp://x.com", "https://u:p@x.com", "https://x.com/?a=1", "https://x.com/#t"]) {
    assert.throws(() => normalizeAddress(bad), Error, bad);
  }
  assert.equal(originPattern("https://example.com/themi"), "https://example.com/*");
});

function fakeThemi(routes) {
  const calls = [];
  const fetchFn = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", headers: init.headers, body: init.body ? JSON.parse(init.body) : null, credentials: init.credentials });
    const [status, body] = routes[`${init.method || "GET"} ${new URL(url).pathname}`] || [404, { error: "no" }];
    return { status, json: async () => body };
  };
  return { fetchFn, calls };
}

test("the API sends the token, never cookies, and reads jobs", async () => {
  const job = { id: 7, items: [{ name: "eggs", qty: 1, search: "eggs", product: null }] };
  const themi = fakeThemi({ "POST /api/safeway/claim": [200, { job }], "POST /api/safeway/jobs/7/results": [200, { ok: true }] });
  const api = createThemiApi({ base: "https://themi.test", token: "swh_abc", fetchFn: themi.fetchFn });
  assert.deepEqual(await api.claim(), job);
  await api.postResults(7, { items: [], stopped: false });
  assert.equal(themi.calls[0].headers.Authorization, "Bearer swh_abc");
  assert.equal(themi.calls[0].credentials, "omit");
  assert.deepEqual(themi.calls[1].body, { items: [], stopped: false });
});

test("no job is null, and a 401 is Revoked", async () => {
  const none = createThemiApi({ base: "https://t", token: "x", fetchFn: fakeThemi({ "POST /api/safeway/claim": [204, null] }).fetchFn });
  assert.equal(await none.claim(), null);
  const revoked = createThemiApi({ base: "https://t", token: "x", fetchFn: fakeThemi({ "POST /api/safeway/claim": [401, { error: "not connected" }] }).fetchFn });
  await assert.rejects(revoked.claim(), Revoked);
});

test("remembered products come from Themi and go back to it", async () => {
  const asked = [];
  const ask = async (msg) => {
    asked.push(msg);
    if (msg.type === "themi-products") return { ok: true, products: [{ name: "Eggs", search: null, product: { id: "1", name: "Lucerne", size: "18 ct" } }, { name: "rice", search: "jasmine rice", product: null }] };
    return { ok: true };
  };
  const memory = createRemoteMemory(ask, itemKey);
  assert.deepEqual(await memory.get("eggs"), { id: "1", name: "Lucerne", size: "18 ct" });
  assert.equal(await memory.get("rice"), null);
  await memory.set("oat milk", { id: "2", name: "Oatly", size: "64 Oz", price: 5.99, inStock: true }, "oat milk");
  assert.deepEqual(asked.at(-1), { type: "themi-set-product", name: "oat milk", product: { id: "2", name: "Oatly", size: "64 Oz", price: 5.99 } });
  assert.equal(asked.filter((m) => m.type === "themi-products").length, 1, "read once per fill");
});

test("a fill's result in Themi's shape", () => {
  const p = { id: "1", name: "Lucerne", size: "18 Count", price: 5.99, inStock: true };
  const body = toResults({
    added: [{ item: "eggs", key: "eggs", qty: 2, product: p }],
    outOfStock: [{ item: "oat milk", key: "oat milk", qty: 1, product: { ...p, id: "2", price: null } }],
    notFound: [{ item: "qzxjvwk", qty: 1 }],
    failed: [{ item: "rice", qty: 3, detail: "no" }],
    stopped: "Sign in to Safeway, then try again.",
  });
  assert.deepEqual(body, {
    items: [
      { name: "eggs", status: "added", qty: 2, product: { id: "1", name: "Lucerne", size: "18 Count", price: 5.99 } },
      { name: "oat milk", status: "out_of_stock", qty: 1, product: { id: "2", name: "Lucerne", size: "18 Count", price: null } },
      { name: "qzxjvwk", status: "not_found", qty: 1, product: null },
      { name: "rice", status: "failed", qty: 3, product: null },
    ],
    stopped: true,
  });
});
