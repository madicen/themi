// The popup: a list box, a "Fill cart" button, and the results of the last fill. The work
// happens in the safeway.com tab (content.js); results arrive through chrome.storage.local.
// Product names come from Safeway, so everything is set with textContent.
(function () {
  const storage = chrome.storage.local;
  const $ = (id) => document.getElementById(id);
  const list = $("list");
  const fillButton = $("fill");
  const status = $("status");
  const results = $("results");

  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }

  function describe(product) {
    const bits = [product.name];
    if (product.size && !product.name.includes(product.size)) bits.push(product.size);
    if (typeof product.price === "number") bits.push("$" + product.price.toFixed(2));
    return bits.join(", ");
  }

  async function safewayTab() {
    const tabs = await chrome.tabs.query({ url: "https://www.safeway.com/*" });
    return tabs.find((t) => t.active) || tabs[0] || null;
  }

  async function send(msg) {
    const tab = await safewayTab();
    if (!tab) return { ok: false, noTab: true, detail: "Open safeway.com in a tab and sign in, then try again." };
    try {
      return await chrome.tabs.sendMessage(tab.id, msg);
    } catch (e) {
      return { ok: false, detail: "Reload the Safeway tab, then try again." };
    }
  }

  function showError(res) {
    status.textContent = res.detail || "Something went wrong.";
    if (res.noTab) {
      const open = el("button", "Open Safeway", "link");
      open.addEventListener("click", () => chrome.tabs.create({ url: "https://www.safeway.com/" }));
      status.append(" ", open);
    }
  }

  function changeLink(li, entry, inCart) {
    const link = el("button", "change", "link");
    link.addEventListener("click", async () => {
      link.disabled = true;
      const box = el("div", "Looking...", "choices muted");
      li.append(box);
      const res = await send({ type: "alternatives", item: entry.item, exclude: entry.product ? entry.product.id : "" });
      box.textContent = "";
      box.className = "choices";
      if (!res || !res.ok) {
        box.textContent = (res && res.detail) || "Couldn't search.";
        return;
      }
      if (!res.products.length) box.textContent = "No other results.";
      const ul = el("ul");
      for (const product of res.products.slice(0, 8)) {
        const option = el("li", describe(product) + (product.inStock ? " " : " (out of stock) "));
        const use = el("button", "use this", "link");
        use.disabled = !product.inStock;
        use.addEventListener("click", async () => {
          use.disabled = true;
          const picked = await send({ type: "choose", key: entry.key, qty: entry.qty || 1, product });
          box.textContent = picked && picked.ok
            ? `Added ${describe(picked.product)}. Next time "${entry.item}" means this one.` +
              (inCart ? ` Remove ${entry.product.name} on safeway.com if you don't want it.` : "")
            : (picked && picked.detail) || (picked && picked.outOfStock ? "That one's out of stock too." : "Couldn't add it.");
        });
        option.append(use);
        ul.append(option);
      }
      box.append(ul);
    });
    li.append(" ", link);
  }

  function section(title, entries, line, withChange, inCart) {
    if (!entries.length) return;
    results.append(el("h2", `${title} (${entries.length})`));
    const ul = el("ul");
    for (const entry of entries) {
      const li = el("li", line(entry));
      if (withChange) changeLink(li, entry, inCart);
      ul.append(li);
    }
    results.append(ul);
  }

  function render(run) {
    results.textContent = "";
    if (!run) return;
    if (run.state === "running") {
      fillButton.disabled = true;
      status.textContent = run.item ? `Adding ${run.item} (${run.done + 1} of ${run.total})...` : "Finishing...";
      return;
    }
    fillButton.disabled = false;
    const r = run.result || {};
    status.textContent = r.stopped ? "" : `Added ${(r.added || []).length} of ${
      (r.added || []).length + (r.notFound || []).length + (r.outOfStock || []).length + (r.failed || []).length
    }.`;
    if (run.fromThemi) results.append(el("p", "This cart was filled for Themi.", "muted"));
    if (r.stopped) results.append(el("p", r.stopped, "stopped"));
    section("Added", r.added || [], (e) => `${e.qty} × ${describe(e.product)}`, true, true);
    section("Out of stock", r.outOfStock || [], (e) => `${e.item}: ${describe(e.product)}`, true, false);
    section("Not found", r.notFound || [], (e) => e.item, false);
    section("Couldn't add", r.failed || [], (e) => `${e.item}: ${e.detail || "Safeway said no"}`, false);
  }

  fillButton.addEventListener("click", async () => {
    if (!ThemiList.parseList(list.value).length) {
      status.textContent = "Type at least one item.";
      return;
    }
    fillButton.disabled = true;
    status.textContent = "Starting...";
    const res = await send({ type: "fill", text: list.value });
    if (!res || !res.ok) {
      fillButton.disabled = false;
      showError(res || {});
    }
  });

  list.addEventListener("input", () => storage.set({ draft: list.value }));
  $("options").addEventListener("click", () => chrome.runtime.openOptionsPage());
  $("open").addEventListener("click", () => chrome.tabs.create({ url: "https://www.safeway.com/" }));

  function showThemi({ themiUrl, themiToken, themiStatus }) {
    $("themi").textContent =
      themiStatus === "revoked"
        ? "Themi disconnected this helper."
        : themiUrl && themiToken
          ? "Connected to Themi: it fills the cart here when you ask it to."
          : "Not connected to Themi.";
  }

  function showTab(why) {
    $("reload").hidden = why !== "reload";
    $("sign-in").hidden = why !== "sign-in";
  }

  storage.get(["draft", "run", "themiUrl", "themiToken", "themiStatus", "themiTab"]).then((s) => {
    if (s.draft) list.value = s.draft;
    render(s.run);
    showThemi(s);
    showTab(s.themiTab);
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.run) render(changes.run.newValue);
    if (area === "local" && changes.themiTab) showTab(changes.themiTab.newValue);
  });
})();
