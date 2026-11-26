/* Same-origin local data, or an explicit user-selected report. No third-party calls. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const number = (value, dp=2) => Number.isFinite(value) ? value.toLocaleString("en-US", {minimumFractionDigits:dp, maximumFractionDigits:dp}) : "—";
  const pct = value => Number.isFinite(value) ? number(value*100,1)+"%" : "—";
  const clock = value => value ? String(value).replace("T"," ").slice(0,19) : "—";
  const local = ["127.0.0.1","localhost"].includes(location.hostname);
  let last = null, imported = false, timer = null, generation = 0, pending = null;
  const form = $("research-form");
  function status(text) { $("lab-status").textContent = text; }
  function validate(data) {
    if (!data || data.schema !== "commodity-monitor-intraday-v1" || !["CL=F","NG=F","GC=F"].includes(data.symbol)
        || !data.analysis || !data.analysis.summary || !data.analysis.params || !data.instrument || !data.source
        || !Array.isArray(data.analysis.trades) || data.analysis.trades.length > 1000
        || !Array.isArray(data.watch) || data.watch.length > 10000 || !Array.isArray(data.sources) || data.sources.length > 3
        || !data.chart || !Array.isArray(data.chart.close) || !Array.isArray(data.chart.ema)) throw Error("This is not a valid intraday research report.");
    for (const key of ["close","ema"]) {
      if (data.chart[key].length > 1000 || !data.chart[key].every(p => Array.isArray(p) && p.length===2 && typeof p[0]==="string" && Number.isFinite(Date.parse(p[0])) && (p[1]===null || Number.isFinite(p[1])))) throw Error("Invalid chart observations.");
    }
    for (const trade of data.analysis.trades) {
      if (typeof trade.date!=="string" || !/^\d{4}-\d{2}-\d{2}$/.test(trade.date) ||
          !["net","gross","cost","long_net","entry","exit"].every(k=>Number.isFinite(trade[k]))) throw Error("Invalid trade observations.");
    }
    return data;
  }
  function render(data) {
    validate(data);
    last = data;
    const a = data.analysis, s = data.source, p = a.params, stats = a.summary;
    $("research").hidden=false;
    $("lab-export").disabled=false;
    form.hidden = !local || imported;
    $("setup").hidden = local || imported;
    $("lab-stamp").textContent = clock(data.generated)+" UTC";
    $("instrument-heading").textContent = data.instrument.name+" · "+s.provider_name;
    $("connection").textContent = imported ? "SAVED REPORT" : "LOCAL COLLECTOR";
    $("price-age").textContent = s.age_minutes === null ? "NO CANDLES" : number(s.age_minutes,1)+" MIN SINCE BAR END";
    $("price-age").className = "pill "+(s.age_minutes !== null && s.age_minutes <=30 ? "current" : "stale");
    $("assumptions").textContent = "Replay: "+p.anchor+" New York anchor · "+p.holding+" minute hold · "+p.slippage+" tick(s) slippage per side · $"+p.fee+" round-trip fee · one full-size contract.";
    $("lab-stats").innerHTML = [
      [stats.count,"Simulated trades"], ["$"+number(stats.net),"Net hypothetical P&L"],
      [pct(stats.win_rate),"Win rate after costs"], ["$"+number(stats.costs),"Total modeled costs"],
    ].map(([v,label])=>"<div><b>"+esc(v)+"</b><span>"+label+"</span></div>").join("");
    const sample = (label,x)=>"<tr><td>"+label+"</td><td>"+esc(x.count)+"</td><td>$"+number(x.net)+"</td><td>$"+number(x.long_baseline)+"</td><td>"+pct(x.win_rate)+"</td><td>$"+number(x.max_drawdown)+"</td></tr>";
    $("split-rows").innerHTML=sample("All eligible sessions",stats)+sample("Earlier 70%",a.earlier)+sample("Later 30%",a.later);
    $("sample-note").textContent = s.bars+" completed bars since "+clock(s.first_bar)+". "+a.excluded+" candidate(s) excluded for incomplete paths. Later sample starts "+(a.split_date || "—")+".";
    $("lab-limitation").textContent=a.limitation;
    $("trade-rows").innerHTML = a.trades.length ? [...a.trades].reverse().map(t=>"<tr><td>"+esc(t.date)+"</td><td>"+(t.direction===1?"Long":"Short")+"</td><td>"+esc(clock(t.entry_time))+"</td><td>"+number(t.entry,data.instrument.dp)+"</td><td>"+number(t.exit,data.instrument.dp)+"</td><td>"+number(t.gross)+"</td><td>"+number(t.cost)+"</td><td>"+number(t.net)+"</td></tr>").join("") : '<tr><td colspan="8" class="empty">No complete sessions for these assumptions.</td></tr>';
    $("watch-rows").innerHTML=data.watch.length ? [...data.watch].reverse().map(t=>"<tr><td>"+esc(clock(t.observed_at))+"</td><td>"+(t.direction===1?"Higher":"Lower")+"</td><td>"+number(t.baseline,data.instrument.dp)+"<small>"+esc(clock(t.baseline_time))+"</small></td><td>"+esc(clock(new Date(t.due_at*1000).toISOString()))+"</td><td>"+esc(t.status==="resolved" ? (t.hit?"Hit":"Miss")+" · "+number(t.outcome,data.instrument.dp) : t.status)+"</td></tr>").join("") : '<tr><td colspan="5" class="empty">No forecasts observed yet. Run the collector around 09:35 New York time; past signals are never backfilled here.</td></tr>';
    $("lab-sources").innerHTML=data.sources.map(x=>"<tr><td>"+esc(x.name)+"</td><td>"+esc(x.status)+"<small>"+esc(x.error || "Delay unverified")+"</small></td><td>"+esc(x.bars)+"</td><td>"+esc(clock(x.last_bar_end))+"</td><td>"+number(x.age_minutes,1)+"</td><td>"+esc(clock(x.last_success))+"</td></tr>").join("");
    window.plotMonitor("intraday-price",[{label:"Completed close",points:data.chart.close},{label:"12 EMA",points:data.chart.ema}],{title:"Five-minute commodity closes and EMA",intraday:true,dp:data.instrument.dp});
    let balance=0, benchmark=0;
    const equity=[], long=[];
    if(a.trades.length) {
      const first = new Date(a.trades[0].date+"T00:00:00Z"); first.setUTCDate(first.getUTCDate()-1);
      equity.push([first.toISOString().slice(0,10),0]); long.push([first.toISOString().slice(0,10),0]);
    }
    a.trades.forEach(t=>{equity.push([t.date,balance+=t.net]);long.push([t.date,benchmark+=t.long_net]);});
    window.plotMonitor("intraday-equity",[{label:"EMA rule",points:equity},{label:"Always buy",points:long}],{title:"Cumulative hypothetical P and L after modeled costs",dp:2});
    if(imported) status("Saved report · captured "+clock(data.generated)+" UTC. No live connection. Reopen the local companion to collect new observations.");
    else if(data.storage_error) status(data.storage_error);
    else if(s.status==="waiting") status("Connecting to the free feed. First collection can take about 20 seconds.");
    else if(s.error) status("Collection problem: "+s.error+". Cached observations remain visible; the collector will retry automatically.");
    else if(s.age_minutes >30) status("Older observations: "+number(s.age_minutes,0)+" minutes since the latest bar ended. The market may be closed or the feed delayed. New forward forecasts are paused.");
    else status("Free feed connected · checks every five minutes while this computer is awake. Quote delay is unverified; this is research data.");
  }
  async function load() {
    if(imported || !local) return;
    const ticket=++generation;
    if(pending) pending.abort();
    pending=new AbortController();
    const timeout=setTimeout(()=>pending?.abort(),12000);
    try {
      const response = await fetch("api/view?"+new URLSearchParams(new FormData(form)),{cache:"no-store",signal:pending.signal});
      if(!response.ok) throw Error("Collector returned HTTP "+response.status);
      const data = await response.json();
      if(ticket===generation && !imported) render(data);
    } catch(error) {
      if(ticket!==generation || imported) return;
      status("Local collector unavailable. Restart Start-Intraday.ps1, then reconnect. Last visible results may be old.");
      $("connection").textContent="DISCONNECTED";
      $("lab-reconnect").hidden=false;
    } finally {clearTimeout(timeout);}
  }
  form.addEventListener("submit", event=>{event.preventDefault();load();});
  $("lab-export").addEventListener("click",()=>{
    if(!last) return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(last,null,2)],{type:"application/json"}));
    const link=document.createElement("a");link.href=url;link.download="private-intraday-"+last.symbol.split("=")[0]+".json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  $("report-file").addEventListener("change",async event=>{
    const file=event.target.files[0];if(!file)return;
    try {
      if(file.size>5_000_000) throw Error("Report must be smaller than 5 MB.");
      const data=validate(JSON.parse(await file.text()));
      imported=true;++generation;pending?.abort();clearInterval(timer);
      render(data);
      $("lab-reconnect").hidden=!local;
    } catch(error) {status("Could not open report: "+error.message);}
    event.target.value="";
  });
  $("lab-reconnect").addEventListener("click",()=>{imported=false;$("lab-reconnect").hidden=true;clearInterval(timer);load();timer=setInterval(load,30000);});
  $("lab-stop").addEventListener("click",async()=>{
    try {
      const response=await fetch("api/stop",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
      if(!response.ok)throw Error();
      clearInterval(timer);++generation;pending?.abort();$("lab-stop").disabled=true;$("connection").textContent="STOPPED";
      status("Local collector stopped. Your saved observations remain on this computer. Run Start-Intraday.ps1 to resume.");
    } catch {status("Could not stop the collector. It may already be offline.");}
  });
  if(local) {
    form.hidden=false;$("lab-stop").hidden=false;load();timer=setInterval(load,30000);
  } else {
    $("setup").hidden=false;
    status("Free intraday research is available through the private companion. Public prices are not streamed here.");
  }
})();
