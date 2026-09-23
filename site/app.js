const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (v, dp = 2) => v == null ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const ord = n => n + ((n % 100 >= 11 && n % 100 <= 13) ? "th" : ({1: "st", 2: "nd", 3: "rd"}[n % 10] || "th"));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function renderTop(d) {
  document.getElementById("stamp").innerHTML = "Updated<br>" + esc(d.generated);
  const r = d.record;
  document.getElementById("record").innerHTML = `
    <div><small>Hit rate</small><b>${r.hit_rate == null ? "–" : r.hit_rate + "%"}</b></div>
    <div><small>Calls graded</small><b>${r.hits}/${r.decided}</b></div>
    <div><small>Open calls</small><b>${r.pending}</b></div>`;

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
  const calls = d.calls;
  document.getElementById("calls").innerHTML = !calls.length
    ? '<div class="empty">No calls yet. Add one in <span class="mono">calls/</span>.</div>'
    : `<table><thead><tr><th>Made</th><th>Metric</th><th>Call</th><th class="thesis">Thesis</th><th>Start → End</th><th>Result</th></tr></thead><tbody>${
      calls.map(c => `<tr>
        <td class="mono">${esc(c.made ?? "")}</td>
        <td>${esc(c.metric)}</td>
        <td class="mono">${c.direction === "up" ? "▲" : c.direction === "down" ? "▼" : ""} ${esc(c.direction)} by ${esc(c.resolve_on ?? "")}</td>
        <td class="thesis">${esc(c.thesis)}${c.note ? `<br><small style="color:var(--muted)">${esc(c.note)}</small>` : ""}</td>
        <td class="mono">${c.start != null ? fmt(c.start) : "–"} → ${c.end != null ? fmt(c.end) : "…"}</td>
        <td><span class="pill ${c.status}">${c.status}</span></td></tr>`).join("")}</tbody></table>`;

  document.getElementById("notes").innerHTML = d.notes.length
    ? d.notes.map(n => `<div class="note"><div class="d">${esc(n.id)}</div>${n.html}</div>`).join("")
    : '<div class="empty">No notes yet.</div>';
}

// Charts live in app2.js (kept separate to keep files small).
document.head.appendChild(Object.assign(document.createElement("script"), { src: "app2.js" }));
