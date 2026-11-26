const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (v, dp = 2) => v == null ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const ord = n => n + ((n % 100 >= 11 && n % 100 <= 13) ? "th" : ({1: "st", 2: "nd", 3: "rd"}[n % 10] || "th"));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function renderTop(d) {
  document.getElementById("stamp").innerHTML = "Updated<br>" + esc(d.generated);
  document.getElementById("record").textContent = "Automated commodity research · No live orders";
  document.getElementById("kpis").innerHTML = d.kpis.map(k => {
    if (k.value == null) return `<div class="kpi"><div class="l">${esc(k.label)}</div><div class="v">–</div></div>`;
    const cls = k.chg_1w > 0 ? "up" : k.chg_1w < 0 ? "down" : "";
    const sign = k.chg_1w > 0 ? "+" : "";
    return `<div class="kpi"><div class="l">${esc(k.label)}<span class="u">${esc(k.unit)}</span></div>
      <div class="v">${fmt(k.value, k.dp)}</div>
      <div class="c ${cls}">${k.chg_1w == null ? "" : sign + fmt(k.chg_1w, k.dp) + " 1w"}</div>
      <div class="c" style="color:var(--muted)">${k.pctile_1y == null ? "" : ord(k.pctile_1y) + " pctile 1y · " + k.date}</div></div>`;
  }).join("");

}

function renderTables(d) {
  const r = d.research;
  document.getElementById("calls").innerHTML = Object.entries(r.signals).map(([k,v]) => `<div class="card"><h3>${esc(k)}</h3><p>${v.signal == null ? "Insufficient data" : ["Down","Neutral","Up"][v.signal+1]} · ${esc(v.date)}</p><p>Historical directional accuracy: ${v.directional_accuracy == null ? "–" : fmt(v.directional_accuracy*100,1)+"%"} (${v.observations} observations)</p><p>${esc(v.method)}</p></div>`).join("") + `<p>Intraday EMA: ${esc(r.intraday.reason)}</p>`;
}

// Charts live in app2.js (kept separate to keep files small).
document.head.appendChild(Object.assign(document.createElement("script"), { src: "app2.js" }));
