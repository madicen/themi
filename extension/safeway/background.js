// The service worker (35d): Chrome's side of lib/worker.js. Calls to Themi go from here,
// where the host permission granted on the options page applies (a content script would be
// held to safeway.com's CORS rules).
importScripts("lib/themi.js", "lib/worker.js");

const ALARM = "themi-poll";

const worker = ThemiWorker.createWorker({
  storage: chrome.storage.local,
  findSafewayTab: async () => (await chrome.tabs.query({ url: "https://www.safeway.com/*" }))[0] || null,
  sendToTab: (tabId, msg) => chrome.tabs.sendMessage(tabId, msg).catch(() => null),
  fetchFn: (url, init) => fetch(url, init),
  setPolling: async (on) => {
    const alarm = await chrome.alarms.get(ALARM);
    if (on && !alarm) await chrome.alarms.create(ALARM, { periodInMinutes: 1 });
    if (!on && alarm) await chrome.alarms.clear(ALARM);
  },
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) worker.poll();
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (sender.id !== chrome.runtime.id || !msg) return false;
  switch (msg.type) {
    case "safeway-tab-ready":
      worker.poll();
      return false;
    case "job-done":
      worker.jobDone(msg.jobId, msg.result || {});
      return false;
    case "themi-products":
      worker.products().then(reply);
      return true;
    case "themi-set-product":
      worker.setProduct(String(msg.name), msg.product).then(reply);
      return true;
    case "themi-test":
      worker.test().then(reply);
      return true;
    default:
      return false;
  }
});
