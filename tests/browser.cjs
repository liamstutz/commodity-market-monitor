const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const assert = require("node:assert/strict");

(async () => {
  fs.mkdirSync(".test-output", { recursive: true });
  const server = spawn("python", ["-m", "http.server", "8765", "--bind", "127.0.0.1", "--directory", "_site"], { stdio: "ignore" });
  let browser;
  try {
    for (let i = 0; i < 50; i++) {
      try { if ((await fetch("http://127.0.0.1:8765/")).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    browser = await chromium.launch();
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("http://127.0.0.1:8765/");
    await page.waitForSelector("#c_wti svg");
    assert.equal(await page.locator(".kpi").count(), 6);
    assert.equal(await page.locator(".chart svg").count(), 4);
    assert.equal(await page.locator(".signal").count(), 4);
    assert.equal(await page.locator("#source-rows tr").count(), 6);
    assert.equal(await page.locator("#error").isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: ".test-output/desktop.png", fullPage: true });
    const initialPath = await page.locator("#c_wti path").first().getAttribute("d");
    await page.locator('[data-range="3"]').click();
    assert.notEqual(await page.locator("#c_wti path").first().getAttribute("d"), initialPath);
    assert.equal(await page.locator('[data-range="3"]').getAttribute("aria-pressed"), "true");
    await page.locator("#price-view").selectOption("spread");
    assert.match(await page.locator("#price-subtitle").innerText(), /minus Brent/);
    const initialReadout = await page.locator("#c_wti .chart-readout").innerText();
    await page.locator("#c_wti svg").focus();
    await page.keyboard.press("ArrowLeft");
    assert.notEqual(await page.locator("#c_wti .chart-readout").innerText(), initialReadout);
    const downloadPromise = page.waitForEvent("download");
    await page.locator("#export").click();
    const download = await downloadPromise;
    await download.saveAs(".test-output/journal.json");
    const exported = JSON.parse(fs.readFileSync(".test-output/journal.json", "utf8"));
    assert.equal(Array.isArray(exported.entries), true);
    assert.equal(exported.issued, exported.entries.length);
    await page.locator('summary').filter({ hasText: "Historical diagnostic" }).click();
    assert.equal(await page.locator("#diagnostics").isVisible(), true);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("http://127.0.0.1:8765/");
    await page.waitForSelector("#c_wti svg");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "Mobile page must not overflow");
    await page.screenshot({ path: ".test-output/mobile.png", fullPage: true });
    await page.locator('[data-range="36"]').click();
    await page.locator("#price-view").selectOption("spread");
    assert.equal(await page.locator("#c_wti svg").isVisible(), true);

    // Exercise a real failed request and user retry without changing production data.
    await page.route("**/data.json*", route => route.fulfill({ status: 503, body: "test outage" }));
    await page.reload();
    await page.locator("#retry").waitFor();
    assert.match(await page.locator("#error").innerText(), /could not be loaded/);
    await page.unroute("**/data.json*");
    await page.locator("#retry").click();
    await page.waitForSelector("#c_wti svg");
    assert.equal(await page.locator("#error").isVisible(), false);

    // Fixture-based states: stale observations and a resolved journal row.
    const payload = JSON.parse(fs.readFileSync("_site/data.json", "utf8"));
    payload.generated = "2020-01-01T00:00:00+00:00";
    for (const signal of Object.values(payload.research.signals)) signal.date = "2020-01-01";
    payload.forward.entries = [{
      issued_at: "2020-01-01T00:00:00Z", metric: "wti", direction: 1,
      start_value: 60, as_of: "2019-12-31", due_on: "2020-01-08",
      status: "resolved", hit: true, move: 2, end_date: "2020-01-08"
    }];
    payload.forward.issued = 1; payload.forward.resolved = 1; payload.forward.pending = 0; payload.forward.hit_rate = 1;
    await page.route("**/data.json*", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) }));
    await page.reload();
    await page.waitForSelector("#c_wti svg");
    assert.equal(await page.locator("#status-banner").isVisible(), true);
    assert.equal(await page.locator(".signal-direction").filter({ hasText: "Paused" }).count(), 4);
    assert.match(await page.locator("#journal-rows").innerText(), /Hit/);
    assert.deepEqual(errors, []);
    console.log("PASS: desktop/mobile rendering, all four charts, range and spread controls, keyboard chart inspection, export, methodology, failed-fetch retry, stale signals and resolved journal.");
    fs.writeFileSync(".test-output/browser-results.json", JSON.stringify({ status: "passed", viewportDesktop: [1440, 1000], viewportMobile: [390, 844], pageErrors: errors }, null, 2));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
