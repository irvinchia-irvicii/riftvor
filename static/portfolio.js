"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const money = (value) => value == null ? "—" : `S$${Number(value).toFixed(2)}`;
  const signed = (value) => value == null ? "—" : `${value >= 0 ? "+" : ""}${money(value)}`;
  const pct = (value) => value == null ? "—" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(1)}%`;
  const tone = (value) => value >= 0 ? "pl-up" : "pl-down";
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));

  function stat(label, value, note = "", className = "") {
    return `<article class="portfolio-stat"><span>${esc(label)}</span><b class="${className}">${value}</b><small>${esc(note)}</small></article>`;
  }

  function allocation(target, rows) {
    $(target).innerHTML = rows.length ? rows.map((row) => `
      <div class="allocation-row">
        <div><b>${esc(row.name)}</b><span>${row.cards} cards · ${money(row.value)}</span></div>
        <strong>${row.share_pct.toFixed(1)}%</strong>
        <div class="allocation-track"><i style="width:${Math.min(100, row.share_pct)}%"></i></div>
      </div>`).join("") : '<p class="hint">No allocation data yet.</p>';
  }

  function render(data) {
    const s = data.summary;
    $("portfolio-loading").classList.add("hidden");
    if (!s.cards) {
      $("portfolio-empty").classList.remove("hidden");
      return;
    }
    $("portfolio-content").classList.remove("hidden");
    $("portfolio-summary").innerHTML = [
      stat("TCGplayer benchmark", money(s.value), `${s.priced_cards} of ${s.cards} cards · via Riftbound.gg`),
      stat("Singapore shop median", money(s.sg_value), `${s.sg_priced_cards} of ${s.cards} cards priced`),
      stat("Cost basis", money(s.paid), `${s.positions} unique positions`),
      stat("Benchmark P/L", signed(s.delta), `${pct(s.return_pct)} on ${money(s.priced_cost)} covered cost`, tone(s.delta)),
      stat("SG vs benchmark", signed(s.sg_vs_benchmark), `${pct(s.sg_vs_benchmark_pct)} across ${s.comparison_cards} matched cards`, tone(s.sg_vs_benchmark)),
    ].join("");
    const dates = [];
    if (s.benchmark_as_of) dates.push(`TCGplayer: ${new Date(s.benchmark_as_of * 1000).toLocaleString()}`);
    if (s.as_of) dates.push(`SG shops: ${new Date(s.as_of * 1000).toLocaleString()}`);
    if (s.fx_rate) dates.push(`USD/SGD ${Number(s.fx_rate).toFixed(4)} (${s.fx_as_of || "latest"})`);
    $("portfolio-asof").textContent = dates.join(" · ");

    const trend = data.trend_30d;
    $("portfolio-trend").innerHTML = trend.status === "ready"
      ? `<div class="trend-value ${tone(trend.delta)}">${pct(trend.change_pct)}</div>
         <p>${money(trend.start_value)} → ${money(trend.end_value)} across ${trend.cards} matched cards.</p>`
      : `<div class="trend-value soft">Collecting history</div><p>Daily snapshots will unlock a meaningful 30-day comparison over time.</p>`;
    $("portfolio-balance").innerHTML = `
      <div class="trend-value">${s.top_holding_pct.toFixed(1)}%</div>
      <p>Your largest priced holding's share of the portfolio. A high number means your value is concentrated in fewer cards.</p>`;

    allocation("portfolio-sets", data.sets);
    allocation("portfolio-folders", data.folders);
    $("portfolio-positions").innerHTML = data.positions.map((row) => `
      <tr>
        <td><b>${row.benchmark_url ? `<a href="${esc(row.benchmark_url)}" target="_blank" rel="noopener">${esc(row.name)}</a>` : esc(row.name)}</b><div class="cmeta">${esc(row.card_key)} · ${esc(row.finish)}</div></td>
        <td>${row.qty}</td><td>${money(row.paid)}</td><td>${money(row.value)}${row.native_unit_value == null ? "" : `<div class="cmeta">${money(row.unit_value)} ea. · US$${Number(row.native_unit_value).toFixed(2)}</div>`}</td>
        <td>${money(row.sg_value)}${row.sg_unit_value == null ? "" : `<div class="cmeta">${money(row.sg_unit_value)} ea. · ${row.shops} shop${row.shops === 1 ? "" : "s"}</div>`}</td>
        <td class="${row.delta == null ? "" : tone(row.delta)}">${row.delta == null ? "—" : `${signed(row.delta)} (${pct(row.return_pct)})`}</td>
        <td class="${row.sg_vs_benchmark == null ? "" : tone(-row.sg_vs_benchmark)}">${row.sg_vs_benchmark == null ? "—" : signed(row.sg_vs_benchmark)}</td>
      </tr>`).join("");

    const labels = { connected: "Connected", search_only: "Search only", not_connected: "Not connected", unavailable: "Unavailable" };
    $("portfolio-sources").innerHTML = data.sources.map((source) => `
      <div class="source-row">
        <div><b>${source.url ? `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.name)}</a>` : esc(source.name)}</b>
        <p>${esc(source.detail)}</p></div>
        <span class="source-status ${source.status}">${labels[source.status] || esc(source.status)}</span>
        ${source.value == null ? "" : `<strong>${money(source.value)}<small>${source.coverage_pct.toFixed(1)}% coverage</small></strong>`}
      </div>`).join("");
    $("portfolio-method").textContent = data.methodology;
  }

  fetch("/api/portfolio")
    .then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Portfolio could not be loaded.");
      return data;
    })
    .then(render)
    .catch((error) => { $("portfolio-loading").textContent = error.message; });
})();
