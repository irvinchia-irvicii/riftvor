/* Riftvor collection view — what you paid vs what it's worth now. */
"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (p) => (p == null ? "—" : "$" + p.toFixed(2));
const signed = (p) => (p == null ? "—" : (p >= 0 ? "+" : "−") + "$" + Math.abs(p).toFixed(2));

function plClass(v) {
  if (v == null) return "";
  return v > 0 ? "pl-up" : v < 0 ? "pl-down" : "";
}

async function load() {
  const resp = await fetch("/api/collection");
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

  const body = $("collBody");
  body.innerHTML = "";
  for (const it of data.items) {
    const tr = document.createElement("tr");
    const foil = it.finish === "foil"
      ? ' <span class="finish-foil">FOIL</span>' : "";
    const when = new Date(it.acquired_at * 1000)
      .toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "2-digit" });
    tr.innerHTML = `
      <td class="card-cell">
        <img src="/api/card_img/${it.card_key}" loading="lazy"
             onerror="this.style.visibility='hidden'">
        <div>
          <div class="cname">${it.name}${foil}</div>
          <div class="cmeta">${it.card_key}${it.store ? " · " + it.store : ""}</div>
        </div>
      </td>
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

  $("collTable").classList.toggle("hidden", !data.items.length);
  $("collEmpty").classList.toggle("hidden", !!data.items.length);
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("button.x");
  if (!btn) return;
  await fetch(`/api/collection/${btn.dataset.id}`, { method: "DELETE" });
  load();
});

load();
