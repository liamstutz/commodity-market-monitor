/* Dependency-free SVG charts. Values always come from the downloaded observations. */
(() => {
  const escape = value => String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const colors = ["#f1a45b", "#89b6d7", "#8dcab1", "#9ba1ad"];
  const format = (value, dp = 2) => Number(value).toLocaleString("en-US", { maximumFractionDigits: dp, minimumFractionDigits: dp });
  const compact = value => Math.abs(value) >= 1000 ? format(value / 1000, 0) + "k" : format(value, Math.abs(value) < 10 ? 1 : 0);

  function plot(id, datasets, options = {}) {
    const host = document.getElementById(id);
    if (!host) return;
    const keys = [...new Set(datasets.flatMap(series => series.points.map(p => p[0])))].sort((a, b) => options.seasonal ? Number(a) - Number(b) : a.localeCompare(b));
    const numbers = datasets.flatMap(series => series.points.map(p => p[1])).filter(Number.isFinite);
    if (!keys.length || !numbers.length) {
      host.innerHTML = '<div class="empty">No valid observations available for this chart.</div>';
      return;
    }
    const W = 640, H = 255, left = 62, right = 12, top = 12, bottom = 32;
    const maps = datasets.map(series => new Map(series.points));
    const xValues = keys.map(key => options.seasonal ? Number(key) : Date.parse(key.includes("T") ? key : key + "T00:00:00Z"));
    const start = xValues[0], end = xValues.at(-1);
    const x = i => left + (xValues[i] - start) / (end - start || 1) * (W - left - right);
    let low = Math.min(...numbers), high = Math.max(...numbers);
    if (options.bars) { low = Math.min(low, 0); high = Math.max(high, 0); }
    const pad = (high - low || Math.max(Math.abs(high), 1)) * .12;
    low -= pad; high += pad;
    const y = value => top + (high - value) / (high - low) * (H - top - bottom);
    let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" tabindex="0" aria-label="' + escape(options.title || id) + '. Use left and right arrow keys to inspect observations."><title>' + escape(options.title || id) + '</title>';
    for (let i = 0; i < 5; i++) {
      const value = low + (high - low) * i / 4;
      svg += '<line x1="' + left + '" x2="' + (W - right) + '" y1="' + y(value) + '" y2="' + y(value) + '" stroke="#2b2f37" stroke-width="1"/>';
      svg += '<text x="' + (left - 10) + '" y="' + (y(value) + 4) + '" text-anchor="end" fill="#9ba1ad" font-size="11" font-family="Consolas,monospace">' + compact(value) + '</text>';
    }
    [...new Set([0, Math.floor((keys.length - 1) / 2), keys.length - 1])].forEach(i => {
      const label = options.seasonal ? "Week " + keys[i] : options.intraday ? new Date(xValues[i]).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" }) : new Date(xValues[i]).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
      svg += '<text x="' + x(i) + '" y="' + (H - 8) + '" text-anchor="' + (i === 0 ? "start" : i === keys.length - 1 ? "end" : "middle") + '" fill="#9ba1ad" font-size="11" font-family="Consolas,monospace">' + escape(label) + '</text>';
    });
    if (options.band) {
      const upper = maps[0], lower = maps[1];
      const indices = keys.map((key, i) => i).filter(i => Number.isFinite(upper.get(keys[i])) && Number.isFinite(lower.get(keys[i])));
      const polygon = indices.map(i => x(i) + "," + y(upper.get(keys[i]))).concat([...indices].reverse().map(i => x(i) + "," + y(lower.get(keys[i]))));
      svg += '<polygon points="' + polygon.join(" ") + '" fill="#89b6d71b"/>';
    }
    datasets.forEach((series, index) => {
      if (series.hiddenLine) return;
      const color = series.color || colors[index % colors.length];
      if (options.bars) {
        const width = Math.max(1, (W - left - right) / keys.length * .65);
        keys.forEach((key, i) => {
          const value = maps[index].get(key);
          if (!Number.isFinite(value)) return;
          svg += '<rect x="' + (x(i) - width / 2) + '" y="' + Math.min(y(value), y(0)) + '" width="' + width + '" height="' + Math.max(.5, Math.abs(y(0) - y(value))) + '" fill="' + (value >= 0 ? "#8dcab1" : "#e79791") + '" opacity=".8"/>';
        });
      } else {
        let path = "", connected = false;
        keys.forEach((key, i) => {
          const value = maps[index].get(key);
          if (!Number.isFinite(value)) { connected = false; return; }
          path += (connected ? "L" : "M") + x(i).toFixed(2) + "," + y(value).toFixed(2);
          connected = true;
        });
        svg += '<path d="' + path + '" fill="none" stroke="' + color + '" stroke-width="' + (series.dashed ? 1.3 : 2) + '"' + (series.dashed ? ' stroke-dasharray="5 4"' : "") + '/>';
      }
    });
    svg += '<line class="crosshair" x1="0" x2="0" y1="' + top + '" y2="' + (H - bottom) + '" stroke="#9ba1ad" stroke-width="1" stroke-dasharray="3 3" opacity="0"/></svg>';
    const legend = datasets.filter(series => !series.hiddenLine).map((series, index) => '<span><i class="swatch" style="background:' + (series.color || colors[index % colors.length]) + '"></i>' + escape(series.label) + '</span>').join("");
    host.innerHTML = '<div class="chart-legend">' + (options.band ? '<span><i class="swatch" style="background:#89b6d7"></i>Prior 5-year range</span>' : "") + legend + '</div>' + svg + '<div class="chart-readout" aria-live="polite"></div>';
    const canvas = host.querySelector("svg"), readout = host.querySelector(".chart-readout"), crosshair = host.querySelector(".crosshair");
    let selected = keys.length - 1;
    function inspect(i, show = true) {
      selected = Math.min(keys.length - 1, Math.max(0, i));
      const key = keys[selected];
      readout.innerHTML = '<span>' + escape(options.seasonal ? "Week " + key : key) + '</span>' + datasets.map((series, index) => {
        const value = maps[index].get(key);
        return Number.isFinite(value) ? '<span>' + escape(series.label) + ' <b>' + format(value, options.dp ?? 2) + '</b></span>' : "";
      }).join("");
      crosshair.setAttribute("x1", x(selected)); crosshair.setAttribute("x2", x(selected)); crosshair.setAttribute("opacity", show ? ".8" : "0");
    }
    canvas.addEventListener("pointermove", event => {
      const bounds = canvas.getBoundingClientRect(), px = (event.clientX - bounds.left) / bounds.width * W;
      let closest = 0, distance = Infinity;
      keys.forEach((_, i) => { const next = Math.abs(x(i) - px); if (next < distance) { closest = i; distance = next; } });
      inspect(closest);
    });
    canvas.addEventListener("pointerleave", () => inspect(keys.length - 1, false));
    canvas.addEventListener("keydown", event => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault(); inspect(selected + (event.key === "ArrowLeft" ? -1 : 1));
      }
    });
    inspect(keys.length - 1, false);
  }

  window.renderCharts = (data, months = 12, priceView = "prices") => {
    const slice = key => {
      const values = data.series[key] || [];
      if (!values.length) return [];
      const cutoff = new Date(values.at(-1)[0] + "T00:00:00Z");
      cutoff.setUTCMonth(cutoff.getUTCMonth() - months);
      return values.filter(p => Date.parse(p[0] + "T00:00:00Z") >= cutoff.getTime());
    };
    plot("c_wti", priceView === "spread" ? [{ label: "WTI − Brent", points: slice("wti_brent") }] : [
      { label: "WTI", points: slice("wti") }, { label: "Brent", points: slice("brent") },
    ], { title: priceView === "spread" ? "WTI minus Brent spot spread" : "WTI and Brent spot prices" });
    plot("c_crack", [{ label: "3-2-1 crack", points: slice("crack_321") }], { title: "NY Harbor 3-2-1 crack spread" });
    plot("c_cot", [{ label: "Managed-money net", points: slice("mm_net"), color: "#8dcab1" }], { bars: true, dp: 0, title: "WTI managed-money net contracts" });
    const s = data.stocks_seasonal || {}, points = key => (s.weeks || []).map((week, i) => [String(week), s[key][i]]);
    plot("c_stocks", [
      { label: "5y max", points: points("max"), hiddenLine: true },
      { label: "5y min", points: points("min"), hiddenLine: true },
      { label: "5y mean", points: points("avg"), color: "#89b6d7", dashed: true },
      { label: String(s.year || "Current"), points: points("current"), color: "#f1a45b" },
    ], { seasonal: true, band: true, dp: 1, title: "Current-year crude inventories versus prior five-year range" });
  };
  window.plotMonitor = plot;
})();
