/* Real Chromium tests against generated fixtures, never provider prices. */
const { chromium } = require("playwright");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const assert = require("node:assert/strict");
(async()=>{
  fs.mkdirSync(".test-output",{recursive:true});
  const fixture = spawnSync("python",["-c",[
    "import sys, pathlib, datetime as dt",
    "sys.path.insert(0, 'pipeline'); sys.path.insert(0, 'tests')",
    "from intraday_server import atomic",
    "from test_intraday import bars",
    "allbars=[]",
    "for i in range(10):",
    " day=dt.date(2026,11,9)+dt.timedelta(days=i)",
    " if day.weekday()<5: allbars.extend(bars(day.isoformat()))",
    "for symbol in ['CL=F','NG=F','GC=F']:",
    " atomic(pathlib.Path('.test-output/intraday-fixture')/(symbol[:2]+'.json'), {'symbol':symbol,'bars':allbars,'watch':[],'status':'cached','provider_name':'TEST FIXTURE - NOT MARKET DATA','last_success':'2026-11-20T00:00:00+00:00'})"
  ].join("\n")],{encoding:"utf8"});
  assert.equal(fixture.status,0,fixture.stderr);
  const server=spawn("python",["pipeline/intraday_server.py","--offline","--port","8767","--data-dir",".test-output/intraday-fixture"],{stdio:"ignore"});
  let browser;
  try {
    for(let i=0;i<50;i++){
      try{if((await fetch("http://127.0.0.1:8767/api/health")).ok)break;}catch{}
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    browser=await chromium.launch();
    const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
    const page=await context.newPage();
    const errors=[];page.on("pageerror",error=>errors.push(error.message));
    await page.goto("http://127.0.0.1:8767/");
    await page.waitForSelector("#intraday-price svg");
    assert.equal(await page.locator(".chart svg").count(),2);
    assert.match(await page.locator("#lab-status").innerText(),/Older observations/);
    assert.equal(await page.locator("#lab-sources tr").count(),3);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const initial=await page.locator("#lab-stats").innerText();
    await page.locator("#fee").fill("15");
    await page.getByRole("button",{name:"Apply assumptions"}).click();
    await page.waitForFunction(()=>document.querySelector("#assumptions").textContent.includes("$15"));
    assert.notEqual(await page.locator("#lab-stats").innerText(),initial);
    await page.locator("#symbol").selectOption("GC=F");
    await page.getByRole("button",{name:"Apply assumptions"}).click();
    await page.waitForFunction(()=>document.querySelector("#instrument-heading").textContent.startsWith("Gold"));
    await page.locator("#intraday-price svg").focus();
    const before=await page.locator("#intraday-price .chart-readout").innerText();
    await page.keyboard.press("ArrowLeft");
    assert.notEqual(await page.locator("#intraday-price .chart-readout").innerText(),before);
    const downloadPromise=page.waitForEvent("download");
    await page.locator("#lab-export").click();
    const download=await downloadPromise;
    await download.saveAs(".test-output/intraday-test-report.json");
    const exported=JSON.parse(fs.readFileSync(".test-output/intraday-test-report.json","utf8"));
    assert.equal(exported.schema,"commodity-monitor-intraday-v1");
    assert.equal(exported.symbol,"GC=F");
    assert.equal(exported.analysis.params.fee,15);
    await page.screenshot({path:".test-output/intraday-desktop.png",fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:".test-output/intraday-mobile.png",fullPage:true});
    await page.locator("#report-file").setInputFiles(".test-output/intraday-test-report.json");
    await page.waitForFunction(()=>document.querySelector("#connection").textContent==="SAVED REPORT");
    assert.equal(await page.locator("#research-form").isVisible(),false);
    await page.locator("#lab-reconnect").click();
    await page.waitForFunction(()=>document.querySelector("#connection").textContent==="LOCAL COLLECTOR");
    await page.route("**/api/view?**",route=>route.fulfill({status:503,body:"test outage"}));
    await page.getByRole("button",{name:"Apply assumptions"}).click();
    await page.waitForFunction(()=>document.querySelector("#connection").textContent==="DISCONNECTED");
    await page.unroute("**/api/view?**");
    await page.locator("#lab-reconnect").click();
    await page.waitForFunction(()=>document.querySelector("#connection").textContent==="LOCAL COLLECTOR");

    // Simulate a public-host page: no hidden request to the local machine or Yahoo.
    const publicPage=await context.newPage();
    const requests=[];
    await publicPage.route("http://public.test/**",route=>{
      const file=new URL(route.request().url()).pathname.split("/").at(-1) || "intraday.html";
      const allowed=["intraday.html","intraday.js","intraday.css","app2.js","style.css"];
      if(!allowed.includes(file))return route.fulfill({status:404,body:""});
      const type=file.endsWith(".js")?"text/javascript":file.endsWith(".css")?"text/css":"text/html";
      return route.fulfill({status:200,contentType:type,body:fs.readFileSync("site/"+file)});
    });
    publicPage.on("request",request=>requests.push(request.url()));
    await publicPage.goto("http://public.test/intraday.html");
    assert.equal(await publicPage.locator("#setup").isVisible(),true);
    assert.equal(requests.some(url=>url.includes("api/view")||url.includes("127.0.0.1")||url.includes("yahoo")),false);
    await publicPage.locator("#report-file").setInputFiles({name:"bad.json",mimeType:"application/json",buffer:Buffer.from('{"schema":"wrong"}')});
    await publicPage.waitForFunction(()=>document.querySelector("#lab-status").textContent.includes("Could not open report"));
    await publicPage.locator("#report-file").setInputFiles(".test-output/intraday-test-report.json");
    await publicPage.waitForSelector("#intraday-price svg");
    assert.equal(await publicPage.locator("#setup").isVisible(),false);
    assert.deepEqual(errors,[]);
    await page.locator("#lab-stop").click();
    await page.waitForFunction(()=>document.querySelector("#connection").textContent==="STOPPED");
    console.log("PASS: intraday desktop/mobile charts, editable costs, commodity selector, keyboard inspection, export/import, outage recovery, public privacy boundary and collector stop.");
  } finally {if(browser)await browser.close();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
