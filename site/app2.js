function renderCharts(d) {
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--line");
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  const base = {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    elements: { point: { radius: 0 }, line: { borderWidth: 1.6, tension: 0 } },
    plugins: { legend: { labels: { boxWidth: 10, boxHeight: 2 } } },
    scales: { x: { ticks: { maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } } },
  };
  const S = d.series;
  const xs = k => S[k].map(p => p[0]), ys = k => S[k].map(p => p[1]);

  new Chart(c_crack, { type: "line", options: { ...base, plugins: { legend: { display: false } } },
    data: { labels: xs("crack_321"), datasets: [{ label: "3-2-1 crack", data: ys("crack_321"), borderColor: css("--accent") }] } });

  const spreadMap = Object.fromEntries(S.wti_brent);
  const brentMap = Object.fromEntries(S.brent);
  new Chart(c_wti, { type: "line",
    options: { ...base, scales: { ...base.scales, y: { position: "left" }, y2: { position: "right", grid: { display: false } } } },
    data: { labels: xs("wti"), datasets: [
      { label: "WTI", data: ys("wti"), borderColor: css("--accent"), yAxisID: "y" },
      { label: "Brent", data: xs("wti").map(t => brentMap[t] ?? null), borderColor: css("--accent2"), yAxisID: "y", spanGaps: true },
      { label: "Spread (rhs)", data: xs("wti").map(t => spreadMap[t] ?? null), borderColor: css("--muted"), borderWidth: 1, borderDash: [4, 3], yAxisID: "y2", spanGaps: true },
    ] } });

  const st = d.stocks_seasonal;
  if (st.weeks) new Chart(c_stocks, { type: "line", options: { ...base, scales: { x: { ...base.scales.x, title: { display: true, text: "Week of year" } } } },
    data: { labels: st.weeks, datasets: [
      { label: "5y max", data: st.max, borderColor: "transparent", backgroundColor: css("--band"), fill: "+1" },
      { label: "5y min", data: st.min, borderColor: "transparent" },
      { label: "5y avg", data: st.avg, borderColor: css("--muted"), borderDash: [4, 3] },
      { label: String(st.year), data: st.current, borderColor: css("--accent"), borderWidth: 2.4 },
    ] } });

  new Chart(c_cot, { type: "bar", options: { ...base, plugins: { legend: { display: false } } },
    data: { labels: xs("mm_net"), datasets: [{ label: "Managed money net", data: ys("mm_net"),
      backgroundColor: ys("mm_net").map(v => v >= 0 ? css("--up") : css("--down")) }] } });

}

fetch("data.json").then(r => r.json()).then(d => { renderTop(d); renderCharts(d); renderTables(d); }).catch(() => {
  document.getElementById("kpis").innerHTML = '<div class="empty">No data yet. The first scheduled update will fill this in.</div>';
});

