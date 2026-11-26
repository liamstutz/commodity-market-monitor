"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (value, dp = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const percent = value => value == null ? "—" : fmt(value * 100, 1) + "%";
const shortNames = { wti: "WTI crude", brent: "Brent crude", wti_brent: "WTI − Brent", crack_321: "3-2-1 crack", crude_stocks: "Crude stocks", mm_net: "Managed money" };
const utc = value => value ? new Date(value).toISOString().replace("T", " ").slice(0, 16) : "Not recorded";
const dayAge = value => Math.floor((Date.now() - Date.parse(value + "T00:00:00Z")) / 86400000);
let currentData = null, chartMonths = 12, priceView = "prices";
let inFlight = false;

function render(data) {
  currentData = data;
  $("stamp").textContent = utc(data.generated);
  $("stamp").dateTime = data.generated;
  const sources = data.sources.map(source => {
    let state = source.state;
    if (source.latest && (dayAge(source.latest) > source.max_age_days || dayAge(source.latest) < 0)) state = "stale";
    else if (state === "current" && Date.now() - Date.parse(source.last_attempt) > 36 * 3600000) state = "unverified";
    return { ...source, state };
  });
  const healthy = sources.filter(source => source.state === "current").length;
  $("health-label").textContent = healthy + "/" + sources.length + " SOURCES VERIFIED";
  $("health-label").classList.toggle("warn", healthy !== sources.length);
  const oldBuild = Date.now() - Date.parse(data.generated) > 36 * 3600000;
  const banner = $("status-banner");
  banner.hidden = healthy === sources.length && !oldBuild;
  banner.textContent = oldBuild ? "This dashboard has not rebuilt in over 36 hours. Check the latest observation dates and source health before interpreting its signals." : "Some source checks are failed, stale or not yet recorded. Cached observations remain visible; new forecasts require a successful source refresh.";
  $("kpis").innerHTML = data.kpis.map(kpi => {
    const change = kpi.chg_1w, stale = kpi.date && dayAge(kpi.date) > (["mm_net", "crude_stocks"].includes(kpi.key) ? 14 : 7);
    return '<div class="kpi"><div class="label">' + esc(shortNames[kpi.key] || kpi.label) + '</div><div class="value">' + fmt(kpi.value, kpi.dp) + '</div><div class="unit">' + esc(kpi.unit) + '</div><div class="change ' + (change > 0 ? "up" : change < 0 ? "down" : "") + '">' + (change == null ? "No prior week" : (change > 0 ? "+" : "") + fmt(change, kpi.dp) + " / 1w") + '</div><div class="date">' + esc(kpi.date || "Unavailable") + (stale ? ' <span class="warn">STALE</span>' : "") + '<br>' + (kpi.pctile_1y == null ? "—" : kpi.pctile_1y + "/100 · 1y percentile") + '</div></div>';
  }).join("");
  $("brief").innerHTML = data.brief.map(item => '<article class="brief-item"><div class="brief-top"><h3>' + esc(shortNames[item.key]) + '</h3><time>' + esc(item.date) + '</time></div><p>' + esc(item.text) + '</p></article>').join("");
  $("signals-grid").innerHTML = Object.entries(data.research.signals).map(([key, signal]) => {
    const stale = signal.date && dayAge(signal.date) > 7;
    const direction = stale ? null : signal.signal;
    const label = direction == null ? "Paused" : direction === 1 ? "Higher" : direction === -1 ? "Lower" : "Neutral";
    const reason = stale ? "The latest observation is over seven days old. New forecasts are paused." : signal.reason;
    return '<article class="signal ' + (direction === 1 ? "positive" : direction === -1 ? "negative" : "") + '"><div class="signal-title">' + esc(shortNames[key]) + '</div><div class="signal-direction ' + (direction === 1 ? "up" : direction === -1 ? "down" : "") + '">' + label + '<span>7d view</span></div><dl><dt>Latest</dt><dd>' + fmt(signal.value) + '</dd><dt>20-obs mean</dt><dd>' + fmt(signal.mean) + '</dd><dt>Z-score</dt><dd>' + fmt(signal.z) + '</dd></dl><p>' + esc(reason) + '</p><div class="signal-date">OBSERVED ' + esc(signal.date || "—") + '</div></article>';
  }).join("");
  $("diagnostics").innerHTML = Object.entries(data.research.signals).map(([key, signal]) => '<tr><td>' + esc(shortNames[key]) + '</td><td>' + fmt(signal.observations, 0) + '</td><td>' + percent(signal.directional_accuracy) + '</td><td>' + percent(signal.up_baseline_accuracy) + '</td></tr>').join("");
  const forward = data.forward;
  $("record").innerHTML = [
    [fmt(forward.issued, 0), "Forecasts issued"], [fmt(forward.pending, 0), "Awaiting outcome"],
    [fmt(forward.resolved, 0), "Resolved forecasts"], [percent(forward.hit_rate), "Forward hit rate"],
  ].map(([value, label]) => '<div><b>' + value + '</b><span>' + label + '</span></div>').join("");
  $("journal-rows").innerHTML = forward.entries.length ? forward.entries.slice(0, 200).map(entry => {
    const result = entry.status === "resolved" ? (entry.hit ? "Hit" : "Miss") : entry.status === "unscored" ? "Unscored" : "Pending";
    return '<tr><td>' + esc(utc(entry.issued_at)) + '</td><td>' + esc(shortNames[entry.metric]) + '</td><td class="' + (entry.direction === 1 ? "up" : "down") + '">' + (entry.direction === 1 ? "Higher" : "Lower") + '</td><td>' + fmt(entry.start_value) + '<small>Observed ' + esc(entry.as_of) + '</small></td><td>' + esc(entry.due_on) + '</td><td><span class="pill ' + (result === "Miss" ? "miss" : entry.status) + '">' + result + '</span>' + (entry.move != null ? '<small>' + (entry.move > 0 ? "+" : "") + fmt(entry.move) + ' · ' + esc(entry.end_date) + '</small>' : "") + '</td></tr>';
  }).join("") : '<tr><td colspan="6" class="empty">No forward forecasts issued yet. The next successful automated refresh will save qualifying signals here.</td></tr>';
  if (forward.entries.length > 200) $("journal-rows").insertAdjacentHTML("beforeend", '<tr><td colspan="6" class="empty">Showing the latest 200 forecasts. Export the journal for the complete record.</td></tr>');
  $("forward-method").textContent = forward.method;
  $("forward-limit").textContent = forward.limitation + (forward.unscored ? " Unscored forecasts: " + forward.unscored + "." : "");
  $("export").disabled = false;
  $("source-rows").innerHTML = sources.map(source => '<tr><td><a href="' + esc(source.url) + '" target="_blank" rel="noopener">' + esc(source.label) + ' ↗</a><small>' + esc(source.frequency) + '</small></td><td>' + esc(source.provider) + '</td><td>' + esc(source.latest || "Unavailable") + '</td><td>' + esc(utc(source.last_success)) + '</td><td><span class="pill ' + esc(source.state) + '">' + esc(source.state) + '</span>' + (source.error ? '<small title="' + esc(source.error) + '">Fetch failed; cache retained</small>' : "") + '</td></tr>').join("");
  $("intraday-reason").textContent = data.research.intraday.reason;
  $("intraday-rule").textContent = data.research.intraday.rule;
  window.renderCharts(data, chartMonths, priceView);
}

async function loadData() {
  if (inFlight) return;
  inFlight = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch("data.json", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    if (data.schema_version !== 2 || !data.research || !data.forward || !Array.isArray(data.sources)) throw new Error("Unexpected dashboard data");
    render(data);
    $("error").hidden = true;
  } catch (error) {
    $("error").hidden = false;
    $("error").innerHTML = (currentData ? "The refresh failed. The last loaded observations remain visible." : "Market data could not be loaded. Check your connection and try again.") + ' <button id="retry" type="button">Retry</button>';
    $("retry").addEventListener("click", loadData);
    if (!currentData) { $("stamp").textContent = "Unavailable"; $("kpis").innerHTML = '<p class="loading">No observations loaded.</p>'; $("health-label").textContent = "DATA UNAVAILABLE"; $("health-label").classList.add("warn"); }
    console.error("Dashboard load failed:", error);
  } finally {
    clearTimeout(timeout);
    inFlight = false;
  }
}

document.querySelectorAll("[data-range]").forEach(button => {
  button.setAttribute("aria-pressed", String(Number(button.dataset.range) === chartMonths));
  button.addEventListener("click", () => {
    chartMonths = Number(button.dataset.range);
    document.querySelectorAll("[data-range]").forEach(other => other.setAttribute("aria-pressed", String(other === button)));
    if (currentData) window.renderCharts(currentData, chartMonths, priceView);
  });
});
$("price-view").addEventListener("change", event => {
  priceView = event.target.value;
  $("price-subtitle").textContent = priceView === "spread" ? "WTI minus Brent spot · $/bbl" : "WTI & Brent spot · $/bbl";
  if (currentData) window.renderCharts(currentData, chartMonths, priceView);
});
$("export").addEventListener("click", () => {
  if (!currentData) return;
  const blob = new Blob([JSON.stringify(currentData.forward, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = "commodity-forecast-journal.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
loadData();
setInterval(loadData, 10 * 60 * 1000);
