// Runs in the page's own world (manifest "world": "MAIN") so it can read safeway.com's
// globals: the store, the sign-in token and the public API keys. It answers content.js
// only, and only with these values; page scripts can already read all of them.
(function () {
  function context() {
    const AB = window.AB || {};
    const ui = AB.userInfo || {};
    const cfg = (window.SWY && window.SWY.CONFIGSERVICE) || {};
    let channel = "delivery";
    try {
      channel = (AB.COMMON && AB.COMMON.getUserChannel && AB.COMMON.getUserChannel()) || "delivery";
    } catch (e) {}
    return {
      storeId: String(ui.branchId || ""),
      banner: String(ui.banner || "safeway"),
      zipCode: String(ui.zipcode || ""),
      channel: String(channel),
      token: String(ui.SWY_SHOP_TOKEN || ""),
      searchKey: String((cfg.searchConfig && cfg.searchConfig.apimProgramSubscriptionKey) || ""),
      cartKey: String(AB.cartapimkey || ""),
    };
  }

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (event.source !== window || !msg || msg.source !== "themi-safeway-ext" || msg.type !== "context") return;
    if (typeof msg.nonce !== "string" || msg.nonce.length < 16) return;
    window.postMessage({ source: "themi-safeway-page", nonce: msg.nonce, ctx: context() }, window.location.origin);
  });
})();
