/* Soraka's Wish collection view — what you paid vs what it's worth now. */
"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (p) => (p == null ? "—" : "$" + p.toFixed(2));
const signed = (p) => (p == null ? "—" : (p >= 0 ? "+" : "−") + "$" + Math.abs(p).toFixed(2));
let folders = [];
let activeFolder = "all";

function plClass(v) {
  if (v == null) return "";
  return v > 0 ? "pl-up" : v < 0 ? "pl-down" : "";
}

async function load() {
  const resp = await fetch("/api/collection");
  if (resp.status === 401) {
    window.location.href = "/?gate=collection";
    return;
  }
  const data = await resp.json();
  const s = data.summary;

  $("collTotals").innerHTML = `
    <div class="coll-stat"><span>Paid</span><b>${fmt(s.paid)}</b></div>
    <div class="coll-stat"><span>Market now</span><b>${fmt(s.value)}</b></div>
    <div class="coll-stat"><span>P/L</span>
      <b class="${plClass(s.delta)}">${signed(s.delta)}</b></div>
    <div class="coll-stat"><span>Cards</span><b>${s.cards}</b></div>
    <div class="coll-stat"><span>Lines</span><b>${s.lines}</b></div>
    ${s.unpriced ? `<div class="coll-note">${s.unpriced} line${s.unpriced > 1 ? "s" : ""}
      out of stock everywhere today — excluded from market value rather
      than guessed.</div>` : ""}`;

  const visibleItems = data.items.filter((item) => {
    if (activeFolder === "all") return true;
    if (activeFolder === "unfiled") return item.folder_id == null;
    return String(item.folder_id) === activeFolder;
  });

  const body = $("collBody");
  body.innerHTML = "";
  for (const it of visibleItems) {
    const tr = document.createElement("tr");
    const foil = it.finish === "foil"
      ? ' <span class="finish-foil">FOIL</span>' : "";
    const when = new Date(it.acquired_at * 1000)
      .toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "2-digit" });
    tr.innerHTML = `
      <td class="card-cell">
        <img src="/api/card_img/${it.card_key}" loading="lazy" data-card-art
             data-card-key="${it.card_key}" data-card-name="${it.name}"
             onerror="this.style.visibility='hidden'">
        <div>
          <div class="cname">${it.name}${foil}</div>
          <div class="cmeta">${it.card_key}${it.store ? " · " + it.store : ""}</div>
        </div>
      </td>
      <td><select class="item-folder" data-id="${it.id}"
          aria-label="Folder for ${it.name}">${folderOptions(it.folder_id)}</select></td>
      <td class="cmeta">${when}</td>
      <td>${it.qty}</td>
      <td>${fmt(it.unit_paid)}</td>
      <td>${fmt(it.paid)}</td>
      <td>${fmt(it.unit_now)}</td>
      <td>${fmt(it.value)}</td>
      <td class="${plClass(it.delta)}">${signed(it.delta)}</td>
      <td><button class="x" data-id="${it.id}" title="Remove">✕</button></td>`;
    body.appendChild(tr);
  }

  $("collTable").classList.toggle("hidden", !visibleItems.length);
  $("collEmpty").classList.toggle("hidden", !!data.items.length);
  $("collFilterEmpty").classList.toggle(
    "hidden", !data.items.length || !!visibleItems.length);
}

function folderOptions(selectedId) {
  const options = ['<option value="">Unfiled</option>'];
  for (const folder of folders) {
    const selected = folder.id === selectedId ? " selected" : "";
    options.push(`<option value="${folder.id}"${selected}>${escapeHtml(folder.name)}</option>`);
  }
  return options.join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
}

async function loadFolders(preferred = null) {
  const resp = await fetch("/api/collection/folders");
  if (!resp.ok) return;
  folders = await resp.json();

  const filter = $("folder-filter");
  const wanted = preferred != null ? String(preferred) : activeFolder;
  filter.innerHTML = `
    <option value="all">All inventory</option>
    <option value="unfiled">Unfiled</option>`;
  for (const folder of folders) {
    const option = document.createElement("option");
    option.value = folder.id;
    option.textContent = `${folder.name} · ${folder.card_count} cards`;
    filter.appendChild(option);
  }
  const valid = wanted === "all" || wanted === "unfiled"
    || folders.some((folder) => String(folder.id) === wanted);
  activeFolder = valid ? wanted : "all";
  filter.value = activeFolder;

  const manualFolder = $("manual-folder");
  const previousManual = manualFolder.value;
  manualFolder.innerHTML = folderOptions(null);
  if (activeFolder !== "all" && activeFolder !== "unfiled") {
    manualFolder.value = activeFolder;
  } else if ([...manualFolder.options].some((option) => option.value === previousManual)) {
    manualFolder.value = previousManual;
  }

  const canEdit = activeFolder !== "all" && activeFolder !== "unfiled";
  $("rename-folder-btn").disabled = !canEdit;
  $("delete-folder-btn").disabled = !canEdit;
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("button.x");
  if (!btn) return;
  await fetch(`/api/collection/${btn.dataset.id}`, { method: "DELETE" });
  await loadFolders();
  load();
});

document.addEventListener("change", async (event) => {
  const select = event.target.closest("select.item-folder");
  if (!select) return;
  const resp = await fetch(`/api/collection/${select.dataset.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder_id: select.value || null }),
  });
  if (!resp.ok) {
    $("folder-status").textContent = "Could not move that card.";
    return;
  }
  $("folder-status").textContent = "Card moved ✓";
  await loadFolders();
  await load();
});

$("folder-filter").addEventListener("change", async (event) => {
  activeFolder = event.target.value;
  const canEdit = activeFolder !== "all" && activeFolder !== "unfiled";
  $("rename-folder-btn").disabled = !canEdit;
  $("delete-folder-btn").disabled = !canEdit;
  if (canEdit) $("manual-folder").value = activeFolder;
  await load();
});

$("create-folder-btn").addEventListener("click", async () => {
  const input = $("new-folder-name");
  const name = input.value.trim();
  if (!name) return;
  const resp = await fetch("/api/collection/folders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    $("folder-status").textContent = data.error || "Could not create folder.";
    return;
  }
  input.value = "";
  $("folder-status").textContent = `Folder “${data.folder.name}” created ✓`;
  await loadFolders(data.folder.id);
  await load();
});

$("rename-folder-btn").addEventListener("click", async () => {
  const folder = folders.find((item) => String(item.id) === activeFolder);
  if (!folder) return;
  const name = prompt("Rename folder", folder.name);
  if (name == null || !name.trim()) return;
  const resp = await fetch(`/api/collection/folders/${folder.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await resp.json().catch(() => ({}));
  $("folder-status").textContent = resp.ok
    ? "Folder renamed ✓" : (data.error || "Could not rename folder.");
  if (resp.ok) await loadFolders(folder.id);
});

$("delete-folder-btn").addEventListener("click", async () => {
  const folder = folders.find((item) => String(item.id) === activeFolder);
  if (!folder) return;
  if (!confirm(`Delete “${folder.name}”? Its cards will move to Unfiled.`)) return;
  const resp = await fetch(`/api/collection/folders/${folder.id}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    $("folder-status").textContent = "Could not delete folder.";
    return;
  }
  activeFolder = "all";
  $("folder-status").textContent = "Folder deleted; its cards are now Unfiled.";
  await loadFolders();
  await load();
});

/* Manual entry for cards the user already owned before using Soraka's Wish. */
const manualForm = $("manual-add-form");
const manualCard = $("manual-card");
const manualOptions = $("manual-card-options");
const manualStatus = $("manual-add-status");
let manualTimer = null;

manualCard.addEventListener("input", () => {
  clearTimeout(manualTimer);
  const query = manualCard.value.trim();
  if (query.length < 2) return;
  manualTimer = setTimeout(async () => {
    const resp = await fetch("/api/autocomplete?q=" + encodeURIComponent(query));
    if (!resp.ok) return;
    const hits = await resp.json();
    manualOptions.innerHTML = "";
    for (const hit of hits) {
      const option = document.createElement("option");
      option.value = hit.card_key;
      option.label = `${hit.name} · ${hit.rarity || hit.set_code}`;
      manualOptions.appendChild(option);
    }
  }, 180);
});

manualForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = manualForm.querySelector("button[type=submit]");
  const values = new FormData(manualForm);
  const acquiredDate = values.get("acquired_date");
  const acquiredAt = acquiredDate
    ? new Date(`${acquiredDate}T12:00:00`).getTime() / 1000 : null;
  button.disabled = true;
  manualStatus.textContent = "Adding inventory…";
  try {
    const resp = await fetch("/api/collection/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_query: values.get("card_query"),
        folder_id: values.get("folder_id") || null,
        finish: values.get("finish"),
        qty: values.get("qty"),
        unit_paid: values.get("unit_paid"),
        store: values.get("store"),
        acquired_at: acquiredAt,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Could not add that card.");
    manualStatus.textContent = `${data.card_key} added to your collection ✓`;
    manualForm.reset();
    manualForm.elements.qty.value = "1";
    if (activeFolder !== "all" && activeFolder !== "unfiled") {
      manualForm.elements.folder_id.value = activeFolder;
    }
    await loadFolders();
    await load();
  } catch (error) {
    manualStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

(async function boot() {
  await loadFolders();
  await load();
})();
