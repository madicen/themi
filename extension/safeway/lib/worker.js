// The service worker's logic (35d), with Chrome's APIs passed in so the tests can drive it.
// While a safeway.com tab is open and the helper is paired, it asks Themi for a cart job
// every minute, hands a claimed job to the tab, and posts what the tab did back to Themi.
(function (root) {
  const Link = typeof module !== "undefined" && module.exports ? require("./themi.js") : root.ThemiLink;
  const MAX_ITEMS = 60;
  const BUSY_FOR_MS = 30 * 60 * 1000; // Themi gives up on a claimed job after 30 minutes

  // A job from Themi is still data: keep only well-formed items.
  function jobItems(job, itemKey) {
    const items = [];
    for (const raw of (job && Array.isArray(job.items) ? job.items : []).slice(0, MAX_ITEMS)) {
      if (!raw || typeof raw.name !== "string" || !raw.name.trim() || raw.name.length > 80) continue;
      const qty = Number.isInteger(raw.qty) && raw.qty >= 1 && raw.qty <= 20 ? raw.qty : 1;
      const search = typeof raw.search === "string" && raw.search.trim() ? raw.search.slice(0, 80) : raw.name;
      const p = raw.product;
      const product =
        p && typeof p.id === "string" && /^\d{1,20}$/.test(p.id)
          ? { id: p.id, name: String(p.name || "").slice(0, 200), size: String(p.size || "").slice(0, 40), price: null, inStock: true }
          : null;
      items.push({ key: itemKey(raw.name), name: raw.name, qty, search, product });
    }
    return items;
  }

  function createWorker({ storage, findSafewayTab, sendToTab, fetchFn, setPolling, now = () => Date.now() }) {
    async function link() {
      const s = await storage.get(["themiUrl", "themiToken", "themiStatus"]);
      if (!s.themiUrl || !s.themiToken || s.themiStatus === "revoked") return null;
      return Link.createThemiApi({ base: s.themiUrl, token: s.themiToken, fetchFn });
    }

    async function revoked() {
      await storage.set({ themiStatus: "revoked" });
      await setPolling(false);
    }

    // -> what happened, for the tests and the logs.
    async function poll() {
      const api = await link();
      if (!api) {
        await setPolling(false);
        return "unpaired";
      }
      const tab = await findSafewayTab();
      if (!tab) {
        await setPolling(false);
        return "no-tab";
      }
      await setPolling(true);
      const { themiBusy } = await storage.get("themiBusy");
      if (themiBusy && now() - themiBusy.at < BUSY_FOR_MS) return "busy";
      let job;
      try {
        job = await api.claim();
      } catch (e) {
        if (e instanceof Link.Revoked) {
          await revoked();
          return "revoked";
        }
        return "error";
      }
      if (!job) return "none";
      await storage.set({ themiBusy: { jobId: job.id, at: now() } });
      const res = await sendToTab(tab.id, { type: "job", job });
      if (!res || !res.ok) {
        // The tab can't take it (opened before the helper was installed, or busy): Themi
        // sends the list with links when the job runs out.
        await storage.set({ themiBusy: null });
        return "tab-refused";
      }
      return "sent";
    }

    async function jobDone(jobId, result) {
      await storage.set({ themiBusy: null });
      const api = await link();
      if (!api) return "unpaired";
      try {
        await api.postResults(jobId, Link.toResults(result));
        return "posted";
      } catch (e) {
        if (e instanceof Link.Revoked) {
          await revoked();
          return "revoked";
        }
        return "error";
      }
    }

    async function ask(fn) {
      const api = await link();
      if (!api) return { ok: false, detail: "The helper isn't connected to Themi." };
      try {
        return { ok: true, ...(await fn(api)) };
      } catch (e) {
        if (e instanceof Link.Revoked) await revoked();
        return { ok: false, detail: String(e.message || e) };
      }
    }

    return {
      poll,
      jobDone,
      products: () => ask(async (api) => ({ products: await api.products() })),
      setProduct: (name, product) => ask(async (api) => (await api.setProduct(name, product), {})),
      test: () => ask(async (api) => (await api.products(), {})),
    };
  }

  const api = { createWorker, jobItems };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ThemiWorker = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
