// The popup (SW1): Themi's grocery list as a checklist (or a list typed here when the helper
// isn't connected), one "Add N to cart" button, and the last fill while it's recent. The
// work happens in the safeway.com tab (content.js); progress and results arrive through
// chrome.storage.local. lib/popup.js holds the logic. Product names come from Safeway, so
// everything is set with textContent.
(function () {
  const storage = chrome.storage.local;
  const P = globalThis.ThemiPopup;
  const SAFEWAY = "https://www.safeway.com/";
  const SEARCH = "https://www.safeway.com/shop/search-results.html?q=";
  const $ = (id) => document.getElementById(id);

  const state = {
    paired: false,
    themiStatus: null,
    themiItems: [],
    waiting: false,
    themiError: false,
    loading: false,
    extras: [],
    unchecked: [],
    run: null,
    tab: { state: "checking" },
  };
  let currentRows = [];

  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }

  const money = (n) => "$" + n.toFixed(2);

  function productLine(product) {
    if (!product) return "";
    const bits = [product.name];
    if (product.size && !product.name.includes(product.size)) bits.push(product.size);
    return bits.join(", ");
  }

  // ----- the Safeway tab ------------------------------------------------------------------

  async function checkTab() {
    const tabs = await chrome.tabs.query({ url: "https://www.safeway.com/*" });
    let found = { state: "none" };
    for (const tab of tabs.sort((a, b) => Number(b.active) - Number(a.active))) {
      let pong = null;
      try {
        pong = await chrome.tabs.sendMessage(tab.id, { type: "ping" });
      } catch (e) {
        pong = null; // no helper code in it: opened before the helper was loaded
      }
      const here = { id: tab.id, windowId: tab.windowId };
      if (pong && pong.ok) {
        found = { state: "ready", ...here };
        break;
      }
      if (pong) found = { state: "sign-in", ...here };
      else if (found.state === "none") found = { state: "reload", ...here };
    }
    state.tab = found;
    render();
  }

  async function showTab() {
    if (!state.tab.id) return chrome.tabs.create({ url: SAFEWAY });
    await chrome.tabs.update(state.tab.id, { active: true });
    await chrome.windows.update(state.tab.windowId, { focused: true });
  }

  async function act(action) {
    if (action === "open") await chrome.tabs.create({ url: SAFEWAY });
    else if (action === "show") await showTab();
    else if (action === "options") chrome.runtime.openOptionsPage();
    else if (action === "retry") loadThemi();
    else if (action === "reload" && state.tab.id) {
      await chrome.tabs.reload(state.tab.id);
      $("notice-text").textContent = "Reloading the Safeway tab…";
      for (const wait of [2500, 5000, 9000]) setTimeout(checkTab, wait);
    }
  }

  // ----- Themi's list ---------------------------------------------------------------------

  async function loadThemi() {
    if (!state.paired) return;
    state.loading = true;
    state.themiError = false;
    render();
    let res = null;
    try {
      res = await chrome.runtime.sendMessage({ type: "themi-list" });
    } catch (e) {
      res = null;
    }
    state.loading = false;
    if (res && res.ok) {
      state.themiItems = res.items || [];
      state.waiting = Boolean(res.waiting);
    } else {
      state.themiError = true;
      const s = await storage.get("themiStatus");
      state.themiStatus = s.themiStatus || state.themiStatus;
    }
    render();
  }

  // ----- rendering --------------------------------------------------------------------------

  function renderHeader() {
    const link = $("link");
    link.textContent = "";
    const dot = el("span", null, "dot");
    let text;
    if (state.themiStatus === "revoked") {
      dot.classList.add("off");
      text = "Disconnected from Themi";
    } else if (state.paired) {
      dot.classList.add("on");
      text = "Connected to Themi";
    } else {
      text = "Not connected to Themi";
    }
    link.append(dot, text);
  }

  function renderNotice() {
    const n = P.notice({ tab: state.tab.state, themiStatus: state.themiStatus, themiError: state.themiError });
    $("notice").hidden = !n;
    if (!n) return;
    $("notice").className = "notice " + n.kind;
    $("notice-text").textContent = n.text;
    const labels = { open: "Open Safeway", reload: "Reload tab", show: "Go to tab", retry: "Try again", options: "Settings" };
    $("notice-action").textContent = labels[n.action];
    $("notice-action").onclick = () => act(n.action);
  }

  function renderProgress(run) {
    const running = P.running(run, Date.now());
    $("progress").hidden = !running;
    if (!running) return;
    const done = run.done || 0;
    const total = run.total || 1;
    $("progress-text").textContent = run.item ? `Adding ${run.item}…` : "Finishing…";
    $("progress-count").textContent = `${Math.min(done + 1, total)} of ${total}`;
    $("progress-bar").style.width = `${Math.round((done / total) * 100)}%`;
  }

  function changeButton(holder, entry, label, inCart) {
    const button = el("button", label, "text-button");
    button.addEventListener("click", async () => {
      button.disabled = true;
      const box = el("div", null, "choices");
      box.append(el("p", "Looking for others…", "note muted"));
      holder.append(box);
      const res = await sendToTab({ type: "alternatives", item: entry.item, exclude: entry.product ? entry.product.id : "" });
      box.textContent = "";
      if (!res || !res.ok) {
        box.append(el("p", (res && res.detail) || "Couldn't search.", "note"));
        return;
      }
      if (!res.products.length) box.append(el("p", "No other results.", "note muted"));
      for (const product of res.products.slice(0, 6)) {
        const row = el("div", null, "choice");
        const bits = [productLine(product)];
        if (typeof product.price === "number") bits.push(money(product.price));
        if (!product.inStock) bits.push("out of stock");
        row.append(el("span", bits.join(" · ")));
        const use = el("button", "Use this", "small-button");
        use.disabled = !product.inStock;
        use.addEventListener("click", async () => {
          for (const b of box.querySelectorAll("button")) b.disabled = true;
          const picked = await sendToTab({ type: "choose", key: entry.key || globalThis.ThemiList.itemKey(entry.item), qty: entry.qty || 1, product });
          box.textContent = "";
          const said = picked && picked.ok
            ? `Added. Next time “${entry.item}” means this one.` + (inCart ? ` The first one is still in the cart; remove it on safeway.com if you don't want it.` : "")
            : (picked && picked.detail) || (picked && picked.outOfStock ? "That one's out of stock too." : "Couldn't add it.");
          box.append(el("p", said, "note"));
        });
        row.append(use);
        box.append(row);
      }
    });
    return button;
  }

  function group(title, entries, build) {
    if (!entries.length) return null;
    const g = el("div", null, "group");
    g.append(el("h3", `${title} · ${entries.length}`));
    for (const entry of entries) g.append(build(entry));
    return g;
  }

  function resultRow(entry, { product, price, action }) {
    const row = el("div", null, "result");
    const line = el("div", null, "result-line");
    const what = el("span", null, "what");
    if (entry.qty > 1) what.append(el("span", `${entry.qty}×`, "qty"));
    what.append(entry.item);
    if (product) what.append(el("span", productLine(product), "product"));
    line.append(what);
    if (price) line.append(el("span", price, "price"));
    if (action) line.append(action(row));
    row.append(line);
    return row;
  }

  function renderResults(run) {
    const fresh = P.freshRun(run, Date.now());
    const show = Boolean(fresh && fresh.state === "done");
    $("results").hidden = !show;
    if (!show) return;
    const r = fresh.result || {};
    const c = P.counts(r);
    $("results-title").textContent = r.stopped && !c.total ? "The fill stopped" : `Added ${c.added} of ${c.total}`;
    const sub = [P.ago(fresh.at, Date.now())];
    if (fresh.fromThemi) sub.push("for Themi");
    if (c.about !== null) sub.push(`about ${money(c.about)}${c.allPriced ? "" : "+"}`);
    $("results-sub").textContent = sub.join(" · ");
    $("results-stopped").hidden = !r.stopped;
    $("results-stopped").textContent = r.stopped || "";
    const body = $("results-body");
    body.textContent = "";
    const groups = [
      group("Out of stock", r.outOfStock || [], (e) =>
        resultRow(e, { product: e.product, action: (row) => changeButton(row, e, "Pick another", false) })),
      group("Not found", r.notFound || [], (e) =>
        resultRow(e, {
          action: () => {
            const b = el("button", "Search Safeway", "text-button");
            b.addEventListener("click", () => chrome.tabs.create({ url: SEARCH + encodeURIComponent(e.item) }));
            return b;
          },
        })),
      group("Couldn't add", r.failed || [], (e) => resultRow(e, { product: e.detail ? { name: e.detail } : null })),
      group("Added", r.added || [], (e) =>
        resultRow(e, {
          product: e.product,
          price: e.product && typeof e.product.price === "number" ? money(e.product.price * (e.qty || 1)) : "",
          action: (row) => changeButton(row, e, "Change", true),
        })),
    ];
    for (const g of groups) if (g) body.append(g);
  }

  function renderList(run) {
    currentRows = P.rows({
      themiItems: state.paired ? state.themiItems : [],
      extras: state.extras,
      unchecked: state.unchecked,
      run: P.recentFill(run, Date.now()),
      waiting: state.waiting,
    });
    const ticked = currentRows.filter((r) => r.checked).length;
    const title = $("list-title");
    title.textContent = state.paired ? "Grocery list " : "Shopping list ";
    if (currentRows.length) title.append(el("span", `${ticked} of ${currentRows.length}`, "count"));
    $("waiting").hidden = !(state.paired && state.waiting);

    const toggleAll = $("toggle-all");
    toggleAll.hidden = currentRows.length < 2;
    const allOn = currentRows.length && ticked === currentRows.length;
    toggleAll.textContent = allOn ? "Untick all" : "Tick all";
    toggleAll.onclick = () => {
      let unchecked = state.unchecked;
      for (const row of currentRows) unchecked = P.toggle(unchecked, row, !allOn);
      save({ unchecked });
    };

    const list = $("rows");
    list.textContent = "";
    currentRows.forEach((row, i) => {
      const li = el("li", null, "row" + (row.checked ? "" : " off"));
      const box = el("input");
      box.type = "checkbox";
      box.id = "row-" + i;
      box.checked = row.checked;
      box.addEventListener("change", () => save({ unchecked: P.toggle(state.unchecked, row, box.checked) }));
      const label = el("label");
      label.htmlFor = box.id;
      const name = el("span", null, "name");
      if (row.qty > 1) name.append(el("span", `${row.qty}×`, "qty"));
      name.append(row.name);
      label.append(name);
      if (row.product) label.append(el("span", productLine(row.product), "product"));
      else if (row.search && row.search !== row.name) label.append(el("span", `searches “${row.search}”`, "product"));
      li.append(box, label);
      if (row.inCart) li.append(el("span", "in cart", "tag in-cart"));
      else if (row.from && row.from !== "groceries") li.append(el("span", row.from, "tag"));
      if (row.extra) {
        const remove = el("button", "×", "remove");
        remove.title = "Remove";
        remove.setAttribute("aria-label", `Remove ${row.name}`);
        remove.addEventListener("click", () =>
          save({ extras: state.extras.filter((e) => e.name.toLowerCase() !== row.name.toLowerCase()) }));
        li.append(remove);
      }
      list.append(li);
    });

    const empty = $("empty");
    empty.hidden = currentRows.length > 0;
    empty.textContent = state.loading
      ? "Getting the grocery list from Themi…"
      : state.paired && !state.themiError
        ? "Themi's grocery list is empty. Add anything else below."
        : "Add what you need below, one at a time or a pasted list.";
  }

  function renderFill(run) {
    const button = $("fill");
    const running = P.running(run, Date.now());
    const ticked = currentRows.filter((r) => r.checked).length;
    button.textContent = running ? "Filling the cart…" : ticked ? `Add ${ticked} to cart` : "Tick something to add";
    button.disabled = running || !ticked || state.tab.state !== "ready";
    button.title = state.tab.state === "ready" ? "" : "Open a signed-in Safeway tab first";
  }

  function render() {
    renderHeader();
    renderNotice();
    renderProgress(state.run);
    renderResults(state.run);
    renderList(state.run);
    renderFill(state.run);
  }

  async function save(values) {
    Object.assign(state, values);
    render();
    await storage.set(values);
  }

  // ----- actions ----------------------------------------------------------------------------

  async function sendToTab(msg) {
    if (state.tab.state !== "ready") await checkTab();
    if (state.tab.state !== "ready") return { ok: false, detail: "Open a signed-in Safeway tab, then try again." };
    try {
      return await chrome.tabs.sendMessage(state.tab.id, msg);
    } catch (e) {
      return { ok: false, detail: "Reload the Safeway tab, then try again." };
    }
  }

  $("fill").addEventListener("click", async () => {
    const items = P.toFill(currentRows);
    if (!items.length) return;
    $("fill").disabled = true;
    $("fill").textContent = "Starting…";
    const res = await sendToTab({ type: "fill", items });
    if (!res || !res.ok) {
      render();
      $("notice").hidden = false;
      $("notice").className = "notice warn";
      $("notice-text").textContent = (res && res.detail) || "Something went wrong.";
      $("notice-action").textContent = "Go to tab";
      $("notice-action").onclick = () => act("show");
    }
  });

  function addFrom(text) {
    if (!text.trim()) return;
    save({ extras: P.addExtras(state.extras, text) });
  }

  $("add-form").addEventListener("submit", (event) => {
    event.preventDefault();
    addFrom($("add").value);
    $("add").value = "";
  });
  $("add").addEventListener("paste", (event) => {
    const text = event.clipboardData && event.clipboardData.getData("text");
    if (text && /\n/.test(text.trim())) {
      event.preventDefault();
      addFrom(text);
    }
  });

  $("dismiss").addEventListener("click", async () => {
    const run = state.run;
    if (!run) return;
    // What went in is done with: typed extras it added go, and the ticks reset.
    const added = new Set(((run.result && run.result.added) || []).map((e) => e.item.toLowerCase()));
    await save({
      run: { ...run, dismissed: true },
      extras: state.extras.filter((e) => !added.has(e.name.toLowerCase())),
      unchecked: [],
    });
  });

  $("options").addEventListener("click", () => chrome.runtime.openOptionsPage());

  // ----- start ------------------------------------------------------------------------------

  storage.get(["extras", "unchecked", "run", "themiUrl", "themiToken", "themiStatus"]).then((s) => {
    state.extras = Array.isArray(s.extras) ? s.extras : [];
    state.unchecked = Array.isArray(s.unchecked) ? s.unchecked : [];
    state.run = s.run || null;
    state.themiStatus = s.themiStatus || null;
    state.paired = Boolean(s.themiUrl && s.themiToken && s.themiStatus !== "revoked");
    storage.remove("draft"); // the old free-text box (before SW1)
    render();
    checkTab();
    loadThemi();
  });

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.run) {
      state.run = changes.run.newValue || null;
      render();
    }
    if (changes.themiStatus) {
      state.themiStatus = changes.themiStatus.newValue || null;
      render();
    }
  });
})();
