/* Real browser + disposable local application. No external provider requests. */
const path = require("node:path");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const pw = require(process.env.PLAYWRIGHT_MODULE || path.resolve(__dirname, "../../web/node_modules/playwright"));

(async () => {
  const url = process.env.FH_TEST_URL;
  assert(url && /^http:\/\/127\.0\.0\.1:\d+$/.test(url), "Only disposable loopback test targets are allowed");
  const out = process.env.FH_BROWSER_OUT || "/tmp";
  const results = [];
  for (const mobile of [false, true]) {
    const label = mobile ? "webkit-iphone" : "chromium-desktop";
    const browser = mobile ? await pw.webkit.launch({headless:true}) : await pw.chromium.launch({headless:true,
      ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {}), args:["--no-sandbox"]});
    try {
      const context = await browser.newContext(mobile ? {...pw.devices["iPhone 13"]} : {viewport:{width:1440,height:1000}});
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", e => errors.push(e.message));
      // Prevent live provider traffic even if the fixture accidentally changes.
      await page.route("**/*", route => route.request().url().startsWith(url) || route.request().url().startsWith("blob:") ? route.continue() : route.abort());
      await page.goto(url);
      await page.getByLabel("Email", {exact:true}).fill(process.env.FH_TEST_EMAIL);
      await page.getByLabel("Password", {exact:true}).fill(process.env.FH_TEST_PASSWORD);
      await page.getByRole("button",{name:"Sign in",exact:true}).click();
      await page.getByRole("heading",{name:"Dashboard",exact:true}).waitFor();
      for (const destination of ["accounts", "contacts", "channels", "content", "media", "emails", "orders", "analytics", "automations", "settings"]) {
        await page.goto(`${url}/${destination}`);
        await page.locator("h1").first().waitFor();
        const width = await page.evaluate(() => ({screen:innerWidth,content:document.documentElement.scrollWidth}));
        assert(width.content <= width.screen + 2, `${label} ${destination} overflows: ${JSON.stringify(width)}`);
      }
      await page.goto(`${url}/accounts`);
      await page.getByRole("button",{name:"New account",exact:true}).click();
      await page.getByLabel("Account name",{exact:true}).fill(`Browser account ${label}`);
      await page.getByRole("button",{name:"Save account",exact:true}).click();
      await page.getByRole("cell",{name:`Browser account ${label}`,exact:true}).waitFor();
      if (!mobile) await page.screenshot({path:path.join(out, "funnelhub-desktop.png"),fullPage:true});
      await page.goto(`${url}/compose`);
      const picker = page.getByTestId("compose-files");
      const chooserPromise = page.waitForEvent("filechooser");
      await picker.click();
      const chooser = await chooserPromise;
      assert(chooser.isMultiple());
      await chooser.setFiles({name:`picker-${label}.png`, mimeType:"image/png", buffer:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0ioAAAAASUVORK5CYII=","base64")});
      await page.getByTestId("compose-text").fill(`Saved from ${label}`);
      await page.getByRole("button",{name:"Save draft",exact:true}).click();
      await page.getByRole("button",{name:`Saved from ${label}`,exact:true}).waitFor();
      assert(await page.getByTestId("compose-submit").isDisabled());
      await page.reload();
      await page.getByRole("button",{name:`Saved from ${label}`,exact:true}).click();
      assert.equal(await page.getByTestId("compose-text").inputValue(), `Saved from ${label}`);
      await page.getByText("Saved image",{exact:true}).waitFor();
      if (mobile) await page.screenshot({path:path.join(out, "funnelhub-iphone.png"),fullPage:true});
      assert.deepEqual(errors, [], `${label} runtime errors`);
      results.push({browser:label,status:"passed",checks:["login","navigation","responsive width","account create","native filechooser event","multipart upload","draft save/reload","publishing disabled"]});
      console.log("PASS browser",label);
      await context.close();
    } finally {await browser.close();}
  }
  fs.writeFileSync(path.join(out,"browser-acceptance.json"), JSON.stringify({results,physical_iphone_tested:false},null,2));
})().catch(error => {console.error(error.message);process.exit(1);});
