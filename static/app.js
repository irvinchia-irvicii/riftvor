/* Farsight front-end — vanilla JS, no build step. */
"use strict";

const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const error = new Error(data.error || `${path} → HTTP ${resp.status}`);
    error.code = data.code || null;
    error.feature = data.feature || null;
    error.status = resp.status;
    throw error;
  }
  return data;
};

let lastResult = null;
let chart = null;

/* ── Sync chips + dormant banner ─────────────────────────────────────────── */

function renderSync(state) {
  if (!state) return;
  const box = $("sync-chips");
  box.innerHTML = "";
  for (const s of STORES) {
    const chip = document.createElement("span");
    chip.className = "chip";
    if (s.live) {
      chip.classList.add("fresh");
      chip.textContent = `${s.name} · live`;
      chip.title = "Queried live per search — no cache";
      box.appendChild(chip);
      continue;
    }
    const meta = (state.ages || {})[s.key];
    if (!meta || meta.age_s == null) {
      chip.classList.add("stale");
      chip.textContent = `${s.name} · —`;
    } else if (!meta.ok) {
      chip.classList.add("down");
      chip.textContent = `${s.name} · down`;
      chip.title = meta.message || "";
    } else {
      const mins = Math.round(meta.age_s / 60);
      chip.classList.add(meta.age_s <= TTL_SECONDS ? "fresh" : "stale");
      chip.textContent = `${s.name} · ${mins < 1 ? "now" : mins + "m"}`;
      chip.title = `${meta.listing_count} listings`;
    }
    box.appendChild(chip);
  }
  const notices = state.dormant_notices || [];
  const banner = $("dormant-banner");
  if (notices.length) {
    banner.textContent = "New store selling singles? " + notices
      .map((n) => `${n.store}: ${n.detail}`).join(" · ");
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

/* ── Comparison table ────────────────────────────────────────────────────── */

const fmt = (p) => (p == null ? "—" : "$" + p.toFixed(2));

function renderResult(result) {
  lastResult = result;
  const head = $("cmp-head");
  head.innerHTML = "<th>Card</th><th></th>";
  for (const s of STORES) head.innerHTML += `<th>${s.name}</th>`;

  const body = $("cmp-body");
  body.innerHTML = "";
  for (const row of result.rows) {
    const tr = document.createElement("tr");
    const foilTag = row.finish === "foil" ? '<span class="finish-foil">FOIL</span>' : "";
    const qty = row.qty > 1 ? `${row.qty}x ` : "";
    tr.innerHTML = `
      <td class="card-cell">
        <img src="/api/card_img/${row.card_key}" loading="lazy"
             onerror="this.style.visibility='hidden'">
        <div>
          <div class="cname" data-key="${row.card_key}" data-finish="${row.finish}"
               data-name="${row.name || row.card_key}">${qty}${row.name || row.card_key}${foilTag}</div>
          <div class="cmeta">${row.card_key}${row.rarity ? " · " + row.rarity : ""}${row.is_alt_art ? " · alt" : ""}</div>
        </div>
      </td>
      <td><button class="rowbtn watch-add" title="Add to watchlist"
            data-key="${row.card_key}" data-finish="${row.finish}"
            data-best="${row.best_price ?? ""}">👁</button></td>`;
    for (const s of STORES) {
      const cell = row.stores[s.key];
      const td = document.createElement("td");
      td.className = "price";
      if (!cell) {
        td.textContent = "—";
      } else if (!cell.in_stock) {
        td.innerHTML = `<a href="${cell.url}" target="_blank" rel="noopener"><span class="oos">${fmt(cell.price)} (OOS)</span></a>`;
      } else {
        if (row.best_price != null && cell.price === row.best_price) td.classList.add("best");
        td.innerHTML = `<a href="${cell.url}" target="_blank" rel="noopener"
          title="${cell.condition}">${fmt(cell.price)}</a>`;
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  $("cmp-table").classList.toggle("hidden", !result.rows.length);

  const un = $("unmatched-box");
  if (result.unmatched && result.unmatched.length) {
    un.textContent = "No match in any store catalog: " +
      result.unmatched.map((u) => u.raw).join(" · ");
    un.classList.remove("hidden");
  } else {
    un.classList.add("hidden");
  }

  renderCarousell(result.carousell);
  renderBasket(result.basket);
}

/* ── Purchase plans ──────────────────────────────────────────────────────── */

function renderBasket(basket) {
  const box = $("plan-box");
  if (!basket || !basket.plans || !basket.plans.length) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  const names = basket.store_names || {};
  const panel = $("planPanel");
  panel.innerHTML = "";

  const makeRow = (plan, isSingle) => {
    const div = document.createElement("div");
    div.className = "plan-row";
    const stores = isSingle
      ? "1 store"
      : `${plan.store_count} store${plan.store_count === 1 ? "" : "s"}`;
    const short = plan.lines_filled < plan.lines_total;
    const cover = `<span class="${short ? "plan-short" : ""}">${plan.lines_filled}/${plan.lines_total} lines</span>`;
    const prem = plan.premium > 0
      ? ` <span class="plan-prem">+${fmt(plan.premium)}</span>` : "";
    div.innerHTML =
      `<div class="plan-head"><span class="plan-name">${plan.label}</span>
         <span class="plan-total">${fmt(plan.total)}</span></div>
       <div class="plan-sub">${stores} · ${cover}${prem}</div>`;
    div.onclick = () => openPlan(plan, names);
    return div;
  };

  for (const plan of basket.plans) panel.appendChild(makeRow(plan, false));

  if (basket.single_store && basket.single_store.length) {
    const head = document.createElement("div");
    head.className = "plan-sechead";
    head.textContent = "If you buy from one store";
    panel.appendChild(head);
    for (const plan of basket.single_store.slice(0, 3)) {
      panel.appendChild(makeRow(plan, true));
    }
  }

  const caveats = [];
  if (basket.assumes_stock_depth) {
    caveats.push("Stores publish in-stock, not how many — multi-copy lines "
      + "assume they can supply the full quantity.");
  }
  if (basket.ambiguous_lines && basket.ambiguous_lines.length) {
    caveats.push("Matched more than one printing (cheapest picked): "
      + basket.ambiguous_lines.slice(0, 4).join(", ")
      + (basket.ambiguous_lines.length > 4 ? "…" : ""));
  }
  $("planCaveat").innerHTML = caveats.map((c) => `<div>${c}</div>`).join("");
}

/* Clipboard needs a secure context (https / localhost). Over plain http
   on a LAN IP navigator.clipboard is undefined, so fall back to the old
   execCommand trick rather than silently doing nothing. */
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

function flash(btn, msg, ms = 1400) {
  const original = btn.textContent;
  btn.textContent = msg;
  btn.disabled = true;
  setTimeout(() => { btn.textContent = original; btn.disabled = false; }, ms);
}

/* Decklist form — 'qty Name' per line — which is what BinderPOS-style
   multi-card search boxes expect. */
function storeAsDecklist(store) {
  return store.lines.map((l) => `${l.qty} ${l.name}`).join("\n");
}

function planToCollectionItems(lines) {
  return lines.map((l) => ({
    card_key: l.card_key, finish: l.finish, qty: l.qty,
    unit_paid: l.unit_price, store: l.store,
  }));
}

async function addToCollection(items, btn, label) {
  try {
    const folderValue = $("plan-folder-select")?.value || "";
    const folderId = folderValue ? parseInt(folderValue, 10) : null;
    const filedItems = items.map((item) => ({ ...item, folder_id: folderId }));
    const r = await api("/api/collection", {
      method: "POST",
      body: JSON.stringify({ items: filedItems, note: label || null }),
    });
    flash(btn, `Added ${r.added} ✓`);
  } catch (err) {
    if (err.code === "account_required" && window.ShopDiffAuth) {
      window.ShopDiffAuth.requireAccount(
        "Sign in to save purchases and build your private collection.");
      flash(btn, "Sign in required");
    } else {
      flash(btn, "Failed");
    }
  }
}

async function loadPlanFolders() {
  if (!window.ShopDiffAuth?.state.authenticated) return;
  try {
    const folders = await api("/api/collection/folders");
    const select = $("plan-folder-select");
    const selected = select.value;
    select.innerHTML = '<option value="">Unfiled</option>';
    for (const folder of folders) {
      const option = document.createElement("option");
      option.value = folder.id;
      option.textContent = folder.name;
      select.appendChild(option);
    }
    if ([...select.options].some((option) => option.value === selected)) {
      select.value = selected;
    }
  } catch { /* account state may have changed; collection action handles it */ }
}

function openPlan(plan, names) {
  loadPlanFolders();
  $("plan-modal-title").textContent = plan.label;
  $("plan-modal-sub").textContent =
    `${fmt(plan.total)} · ${plan.cards_total} cards · `
    + `${plan.lines_filled}/${plan.lines_total} lines`
    + (plan.note ? ` · ${plan.note}` : "");

  const allLines = plan.by_store.flatMap((s) => s.lines);
  const addAll = $("plan-add-all");
  addAll.textContent = "+ Add all to collection";
  addAll.disabled = false;
  addAll.onclick = () =>
    addToCollection(planToCollectionItems(allLines), addAll, plan.label);

  const body = $("plan-modal-body");
  body.innerHTML = "";
  for (const store of plan.by_store) {
    const sec = document.createElement("div");
    sec.className = "plan-store";

    const head = document.createElement("div");
    head.className = "plan-store-head";
    head.innerHTML = `<b>${names[store.store] || store.store}</b>`;

    const tools = document.createElement("span");
    tools.className = "plan-store-tools";

    const copyBtn = document.createElement("button");
    copyBtn.className = "mini";
    copyBtn.textContent = "Copy list";
    copyBtn.title = "Copy this shop's cards as 'qty Name' per line";
    copyBtn.onclick = async () => {
      const ok = await copyText(storeAsDecklist(store));
      flash(copyBtn, ok ? "Copied ✓" : "Copy failed");
    };
    tools.appendChild(copyBtn);

    // Only Hideout has a bulk-entry page to paste into (probed Aug 2026).
    const cfg = STORES.find((s) => s.key === store.store);
    if (cfg && cfg.multi_search) {
      const link = document.createElement("a");
      link.className = "mini";
      link.href = cfg.multi_search;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Paste →";
      link.title = "Open this shop's multi-card search";
      tools.appendChild(link);
    }

    const addBtn = document.createElement("button");
    addBtn.className = "mini";
    addBtn.textContent = "+ Collection";
    addBtn.title = "Add just this shop's cards at these prices";
    addBtn.onclick = () => addToCollection(
      planToCollectionItems(store.lines), addBtn,
      `${plan.label} — ${names[store.store] || store.store}`);
    tools.appendChild(addBtn);

    const sub = document.createElement("span");
    sub.className = "plan-store-sub";
    sub.textContent = fmt(store.subtotal);
    tools.appendChild(sub);

    head.appendChild(tools);
    sec.appendChild(head);

    const ul = document.createElement("ul");
    for (const line of store.lines) {
      const li = document.createElement("li");
      const qty = line.qty > 1 ? `${line.qty}× ` : "";
      const foil = line.finish === "foil"
        ? ' <span class="finish-foil">FOIL</span>' : "";
      li.innerHTML =
        `<a href="${line.url}" target="_blank" rel="noopener">${qty}${line.name}${foil}</a>
         <span class="cmeta">${line.card_key}</span>
         <span class="plan-line-cost">${fmt(line.line_cost)}</span>`;
      ul.appendChild(li);
    }
    sec.appendChild(ul);
    body.appendChild(sec);
  }
  if (plan.missing && plan.missing.length) {
    const miss = document.createElement("div");
    miss.className = "plan-missing";
    miss.textContent = "Nothing in stock for: " + plan.missing.join(" · ");
    body.appendChild(miss);
  }
  $("plan-modal").classList.remove("hidden");
}

$("plan-modal-close").onclick = () => $("plan-modal").classList.add("hidden");
$("plan-modal").addEventListener("click", (e) => {
  if (e.target === $("plan-modal")) $("plan-modal").classList.add("hidden");
});

function renderCarousell(items) {
  const panel = $("carousell-panel");
  const body = $("carousell-body");
  if (!items || !items.length) { panel.classList.add("hidden"); return; }
  body.innerHTML = "";
  for (const it of items) {
    const div = document.createElement("div");
    div.className = "caro-item";
    div.innerHTML = `<a href="${it.url}" target="_blank" rel="noopener">${it.title}</a>
      <span class="p">${fmt(it.price)}</span>`;
    body.appendChild(div);
  }
  panel.classList.remove("hidden");
}

/* ── Search / refresh / export ───────────────────────────────────────────── */

async function doSearch(force = false) {
  const btn = $("search-btn");
  $("ac-box").classList.add("hidden");
  btn.disabled = true;
  $("status-line").textContent = force
    ? "Syncing all stores (forced)…" : "Checking store freshness…";
  const t0 = performance.now();
  try {
    const result = await api("/api/search", {
      method: "POST",
      body: JSON.stringify({ list_text: $("buylist").value, force }),
    });
    renderSync(result.sync);
    renderResult(result);
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    const synced = (result.sync.summary.synced || []).length;
    $("status-line").textContent =
      `${result.rows.length} rows in ${secs}s ` +
      (synced ? `(synced ${synced} store${synced > 1 ? "s" : ""})` : "(all within TTL)");
  } catch (err) {
    if (err.code === "account_required" && window.ShopDiffAuth) {
      $("status-line").textContent = "Sign in to search more than one card.";
      window.ShopDiffAuth.requireAccount(
        "Create a free account to search an entire deck or buy list at once.");
    } else {
      $("status-line").textContent = "Search failed: " + err.message;
    }
  } finally {
    btn.disabled = false;
  }
}

$("search-btn").onclick = () => doSearch(false);
$("refresh-btn").onclick = async () => {
  $("refresh-btn").disabled = true;
  $("status-line").textContent = "Force-refreshing all stores…";
  try {
    const state = await api("/api/refresh", { method: "POST", body: "{}" });
    renderSync(state);
    $("status-line").textContent = "Stores refreshed.";
    if ($("buylist").value.trim()) doSearch(false);
  } catch (err) {
    $("status-line").textContent = "Refresh failed: " + err.message;
  } finally {
    $("refresh-btn").disabled = false;
  }
};

$("export-btn").onclick = async () => {
  const resp = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ list_text: $("buylist").value }),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    if (data.code === "account_required" && window.ShopDiffAuth) {
      $("status-line").textContent = "Sign in to export a multi-card list.";
      window.ShopDiffAuth.requireAccount(
        "Create a free account to export multi-card comparisons.");
    } else {
      $("status-line").textContent = data.error || "Export failed.";
    }
    return;
  }
  const blob = await resp.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (resp.headers.get("Content-Disposition") || "")
    .split("filename=")[1] || "farsight.xlsx";
  a.click();
  URL.revokeObjectURL(a.href);
};

/* ── Autocomplete (current textarea line) ────────────────────────────────── */

const ta = $("buylist");
const acBox = $("ac-box");
let acSel = -1;

$("clear-btn").onclick = () => {
  ta.value = "";
  lastResult = null;
  acBox.innerHTML = "";
  acBox.classList.add("hidden");
  $("status-line").textContent = "Buy list cleared.";
  $("cmp-body").innerHTML = "";
  $("cmp-table").classList.add("hidden");
  $("unmatched-box").classList.add("hidden");
  $("carousell-panel").classList.add("hidden");
  $("plan-box").classList.add("hidden");
  $("plan-modal").classList.add("hidden");
  ta.focus();
};

function currentLine() {
  const pos = ta.selectionStart;
  const before = ta.value.slice(0, pos);
  const start = before.lastIndexOf("\n") + 1;
  const lineEnd = ta.value.indexOf("\n", pos);
  return { start, end: lineEnd === -1 ? ta.value.length : lineEnd,
           text: before.slice(start) };
}

let acTimer = null;
ta.addEventListener("input", () => {
  clearTimeout(acTimer);
  acTimer = setTimeout(async () => {
    const { text } = currentLine();
    const q = text.replace(/^\d+\s*[xX]?\s*/, "");
    if (q.length < 2) { acBox.classList.add("hidden"); return; }
    const hits = await api("/api/autocomplete?q=" + encodeURIComponent(q));
    if (!hits.length) { acBox.classList.add("hidden"); return; }
    acBox.innerHTML = "";
    acSel = -1;
    for (const h of hits) {
      const div = document.createElement("div");
      div.innerHTML = `${h.name}<span class="k">${h.card_key}${h.rarity ? " · " + h.rarity : ""}</span>`;
      div.onclick = () => pickAc(h);
      acBox.appendChild(div);
    }
    acBox.classList.remove("hidden");
  }, 180);
});

function pickAc(hit) {
  const { start, end, text } = currentLine();
  const qtyMatch = text.match(/^(\d+\s*[xX]?\s*)/);
  const prefix = qtyMatch ? qtyMatch[1] : "";
  ta.value = ta.value.slice(0, start) + prefix + hit.card_key +
    ta.value.slice(end);
  acBox.classList.add("hidden");
  ta.focus();
}

ta.addEventListener("keydown", (e) => {
  if (acBox.classList.contains("hidden")) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) doSearch(false);
    return;
  }
  const items = [...acBox.children];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    acSel = (acSel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((el, i) => el.classList.toggle("sel", i === acSel));
  } else if (e.key === "Enter" && acSel >= 0) {
    e.preventDefault();
    items[acSel].click();
  } else if (e.key === "Escape") {
    acBox.classList.add("hidden");
  }
});
document.addEventListener("click", (e) => {
  if (!acBox.contains(e.target) && e.target !== ta) acBox.classList.add("hidden");
});

/* ── Saved buy lists ─────────────────────────────────────────────────────── */

async function loadSavedLists() {
  const lists = await api("/api/buylists");
  const ul = $("saved-lists");
  ul.innerHTML = "";
  for (const l of lists) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.textContent = l.name;
    a.onclick = () => { ta.value = l.content; $("save-name").value = l.name; };
    const x = document.createElement("button");
    x.className = "x";
    x.textContent = "✕";
    x.onclick = async () => {
      await api("/api/buylists/" + encodeURIComponent(l.name), { method: "DELETE" });
      loadSavedLists();
    };
    li.append(a, x);
    ul.appendChild(li);
  }
}

$("save-btn").onclick = async () => {
  const name = $("save-name").value.trim();
  if (!name) return;
  await api("/api/buylists", {
    method: "POST",
    body: JSON.stringify({ name, content: ta.value }),
  });
  loadSavedLists();
};

/* ── Watchlist ───────────────────────────────────────────────────────────── */

async function loadWatchlist() {
  const items = await api("/api/watchlist");
  const ul = $("watchlist");
  ul.innerHTML = "";
  for (const w of items) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.innerHTML = `${w.name || w.card_key}${w.finish === "foil" ? " (foil)" : ""}
      — <span class="${w.triggered ? "hit" : ""}">${fmt(w.best_price)}</span>
      / target ${fmt(w.target_price)}`;
    a.onclick = () => openHistory(w.card_key, w.finish, w.name || w.card_key);
    const x = document.createElement("button");
    x.className = "x";
    x.textContent = "✕";
    x.onclick = async () => {
      await api(`/api/watchlist/${w.card_key}/${w.finish}`, { method: "DELETE" });
      loadWatchlist();
    };
    li.append(a, x);
    ul.appendChild(li);
  }
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".watch-add");
  if (!btn) return;
  const suggested = btn.dataset.best || "";
  const target = prompt(
    `Alert when best price ≤ … SGD for ${btn.dataset.key} (${btn.dataset.finish})`,
    suggested);
  if (target == null || target === "") return;
  await api("/api/watchlist", {
    method: "POST",
    body: JSON.stringify({
      card_key: btn.dataset.key,
      finish: btn.dataset.finish,
      target_price: parseFloat(target),
    }),
  });
  loadWatchlist();
});

/* ── History modal ───────────────────────────────────────────────────────── */

document.addEventListener("click", (e) => {
  const el = e.target.closest(".cname");
  if (el) openHistory(el.dataset.key, el.dataset.finish, el.dataset.name);
});

async function openHistory(cardKey, finish, name) {
  const data = await api(
    `/api/history/${cardKey}?finish=${encodeURIComponent(finish || "")}`);
  $("modal-title").textContent = name;
  $("modal-sub").textContent = `${cardKey} · ${finish || "all finishes"} · 90 days`;
  $("modal-art").src = `/api/card_img/${cardKey}`;
  $("modal").classList.remove("hidden");
  const palette = ["#7b5cff", "#4dd0e1", "#7dd87d", "#ffb454", "#ff6b6b", "#c792ea"];
  const datasets = Object.entries(data.series).map(([key, points], i) => {
    const [store, fin] = key.split(":");
    return {
      label: (data.store_names[store] || store) + (fin === "foil" ? " (foil)" : ""),
      data: points.map((p) => ({ x: p.t * 1000, y: p.price })),
      borderColor: palette[i % palette.length],
      backgroundColor: palette[i % palette.length],
      tension: 0.2,
      pointRadius: 2,
      spanGaps: true,
    };
  });
  if (chart) chart.destroy();
  chart = new Chart($("history-chart"), {
    type: "line",
    data: { datasets },
    options: {
      scales: {
        x: { type: "linear",
             ticks: { callback: (v) => new Date(v).toLocaleDateString("en-SG",
               { day: "numeric", month: "short" }), maxTicksLimit: 8,
               color: "#8b93a9" },
             grid: { color: "#2c3347" } },
        y: { ticks: { callback: (v) => "$" + v, color: "#8b93a9" },
             grid: { color: "#2c3347" } },
      },
      plugins: { legend: { labels: { color: "#e8eaf2" } } },
    },
  });
}

$("modal-close").onclick = () => $("modal").classList.add("hidden");
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal")) $("modal").classList.add("hidden");
});

/* ── Boot ────────────────────────────────────────────────────────────────── */

(async function boot() {
  try {
    const state = await api("/api/state");
    renderSync(state);
  } catch { /* first load before any sync — chips stay empty */ }
  const authState = window.ShopDiffAuth
    ? await window.ShopDiffAuth.ready : { authenticated: false };
  if (authState.authenticated) loadSavedLists();
  loadWatchlist();
})();
