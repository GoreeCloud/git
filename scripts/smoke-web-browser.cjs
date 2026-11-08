#!/usr/bin/env node
"use strict";
/**
 * Opt-in real-browser acceptance for the local owner-only GoreeCloud Git UI.
 * Requires an independently reviewed external Playwright installation.
 * Run only in a disposable Linux NETWORK namespace with synthetic Git data.
 * The application has no Node or Playwright runtime dependency.
 */
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const net = require("node:net");
const {spawn, spawnSync} = require("node:child_process");

function requireOfflineNamespace() {
  if (process.platform !== "linux" || process.getuid() === 0) {
    throw new Error("Only a non-root Linux developer may run the browser drill.");
  }
  const selfNet = fs.readlinkSync("/proc/self/ns/net");
  // Inside an unprivileged user namespace /proc/1/ns/net may be EACCES.
  // Require an operator-supplied preflight recording from *before* entering
  // the new namespace, as well as the actual --unshare-net Bubblewrap flag.
  const hostNet = process.env.GCGIT_HOST_NET_NS;
  if (!hostNet || !/^net:\[[0-9]+\]$/.test(hostNet) || selfNet === hostNet) {
    throw new Error("Refusing browser launch without separately identified network namespace.");
  }
  if (process.argv.length !== 2) {
    throw new Error("No arguments; run the documented isolated acceptance fixture.");
  }
}

function command(bin, args, env, timeout = 20000) {
  const output = spawnSync(bin, args, {
    env, cwd: path.resolve(__dirname, ".."), encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"], timeout,
  });
  if (output.status !== 0 || output.error) {
    throw new Error("Disposable fixture command failed: " + path.basename(bin));
  }
  return output.stdout.trim();
}

async function availablePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close((err) => err ? reject(err) : resolve(port));
    });
  });
}

async function waitUntilReady(url, token, child) {
  const header = "Basic " + Buffer.from("owner:" + token).toString("base64");
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) throw new Error("Disposable UI server stopped.");
    try {
      const response = await fetch(url, {
        headers: {Authorization: header}, signal: AbortSignal.timeout(1000),
      });
      if (response.status === 200) return;
    } catch (_) {
      // The bounded startup probe retries only within the isolated namespace.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Disposable UI server failed its authenticated health probe.");
}

async function assertSampledTextContrast(page, mode, pairs) {
  // Browser-computed, opaque foreground/background samples only. This is
  // deliberately not an exhaustive alpha-composited WCAG audit.
  const outcomes = await page.evaluate((samples) => {
    function rgb(css) {
      const match = /^rgba?\(([^)]+)\)$/.exec(css);
      if (!match) throw new Error("Unexpected browser color format");
      const values = match[1].split(/[,\s/]+/).filter(Boolean).map(Number);
      if (values.length < 3 || values.slice(0, 3).some((v) => !Number.isFinite(v))
          || (values.length >= 4 && values[3] !== 1)) {
        throw new Error("Non-opaque contrast sample");
      }
      return values.slice(0, 3);
    }
    function luminance(values) {
      const linear = values.map((v) => {
        const x = v / 255;
        return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
      });
      return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
    }
    return samples.map(({foreground, background}) => {
      const a = document.querySelector(foreground);
      const b = document.querySelector(background);
      if (!a || !b) throw new Error("Missing expected contrast sample");
      const fg = luminance(rgb(getComputedStyle(a).color));
      const bg = luminance(rgb(getComputedStyle(b).backgroundColor));
      return {foreground, background,
        ratio: (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05)};
    });
  }, pairs);
  for (const sample of outcomes) {
    assert.ok(sample.ratio >= 4.5,
      mode + " browser-computed text contrast below 4.5:1 for "
      + sample.foreground + " / " + sample.background
      + " (" + sample.ratio.toFixed(2) + ":1)");
  }
  console.log("PASS " + mode + " " + outcomes.length
    + " sampled opaque browser-computed text contrast pairs >= 4.5:1.");
}

async function auditWithAvailableAxe(page, name, phase, evidenceDir) {
  // This diagnostic depends on the operator's already installed axe-core.
  // It is not a shipping dependency and never calls an external service.
  let axe;
  try {
    axe = require("axe-core");
  } catch (error) {
    if (error.code === "MODULE_NOT_FOUND"
        && String(error.message).includes("Cannot find module 'axe-core'")) {
      console.log("SKIP: axe-core not installed; automated A/AA screen is optional.");
      return;
    }
    throw error;
  }
  await page.evaluate(axe.source);
  const result = await page.evaluate(async () => {
    if (!window.axe) throw new Error("Axe diagnostics failed to initialize.");
    const report = await window.axe.run(document, {
      runOnly: {type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]},
    });
    return {
      passes: report.passes.length,
      violations: report.violations.map((item) => ({
        id: item.id, impact: item.impact, nodes: item.nodes.length,
      })),
      incomplete: report.incomplete.map((item) => ({
        id: item.id, impact: item.impact, nodes: item.nodes.length,
      })),
    };
  });
  // Keep only counts/rule IDs and never write credentials or page content.
  fs.writeFileSync(path.join(evidenceDir, name + "-" + phase + "-axe.json"),
    JSON.stringify({engine: "axe-core " + axe.version, page: phase, ...result}, null, 2) + "\n",
    {encoding: "utf8", mode: 0o600});
  assert.deepEqual(result.violations, [],
    "Automated A/AA violations on " + phase + ": " + JSON.stringify(result.violations));
  console.log("PASS " + phase + " axe-core " + axe.version + ": "
    + result.passes + " passed rules, zero detected violations, "
    + result.incomplete.length + " incomplete rules within this screen; manual review still required.");
}

async function acceptBrowser(name, browserType, url, token, evidenceDir, port) {
  const options = {headless: true, timeout: 15000};
  // Chromium's *inner* sandbox is unavailable inside this unprivileged
  // Bubblewrap namespace. The preflight above requires independent network
  // isolation and the operator also mounts the inspected UI source read-only.
  if (name === "chromium") options.chromiumSandbox = false;
  const browser = await browserType.launch(options);
  try {
    const context = await browser.newContext({
      viewport: {width: 1440, height: 900},
      deviceScaleFactor: 1,
      colorScheme: "light",
      reducedMotion: "reduce",
      httpCredentials: {username: "owner", password: token},
    });
    try {
      // Network namespace prevents external egress; observe all requests
      // without Chromium Fetch interception, which can alter Origin headers.
      const externalRequests = [];
      context.on("request", (request) => {
        const destination = new URL(request.url());
        if (destination.protocol !== "http:" || destination.hostname !== "127.0.0.1"
          || destination.port !== String(port)) {
          externalRequests.push(destination.origin);
        }
      });
      const anonymous = await browser.newContext();
      try {
        const denied = await anonymous.request.get(url);
        assert.equal(denied.status(), 401, "Private home must require auth.");
      } finally {
        await anonymous.close();
      }

      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const home = await page.goto(url, {waitUntil: "load"});
      assert.equal(home.status(), 200);
      assert.equal(home.headers()["referrer-policy"], "same-origin");
      assert.equal(await page.locator("html").getAttribute("data-gc-mode"), "light");
      assert.match(await page.locator("h1").innerText(), /Private repositories/);
      assert.equal(await page.getByRole("navigation", {name: "Primary navigation"}).count(), 1);
      assert.equal(await page.getByRole("link", {name: "Skip to content"}).count(), 1);
      await page.keyboard.press("Tab");
      const focused = await page.evaluate(() => {
        const element = document.activeElement;
        return element && element.textContent.trim();
      });
      assert.equal(focused, "Skip to content", "First keyboard focus is skip link.");
      await page.keyboard.press("Enter");
      assert.equal(new URL(page.url()).hash, "#main-content");

      await page.getByRole("link", {name: "example"}).click();
      assert.match(await page.locator("h1").innerText(), /example/);
      assert.match(await page.locator("ol.timeline").innerText(), /Browser synthetic commit/);
      await page.getByRole("navigation", {name: "Primary navigation"})
        .getByRole("link", {name: "Repositories"}).click();

      // WCAG 1.4.10 reflow: a 320-CSS-pixel layout corresponds to a
      // 1280-physical-pixel desktop narrowed by a 400% browser zoom.
      // These viewport tests DO NOT change the browser's actual zoom setting;
      // do not claim a native 400%-zoom test based on them alone.
      const widths = [320, 375, 640, 768, 1440];
      for (const width of widths) {
        const height = width === 375 ? 812 : width === 768 ? 1024 : 900;
        await page.setViewportSize({width, height});
        const overflow = await page.evaluate(() => {
          const el = document.documentElement;
          return Math.max(el.scrollWidth, document.body.scrollWidth) - el.clientWidth;
        });
        assert.ok(overflow <= 1, "Horizontal overflow at " + width + "px: " + overflow);
        const heading = page.getByRole("heading", {name: "Private repositories"});
        assert.equal(await heading.isVisible(), true);
        // No repository card or navigation action may be clipped outside
        // the viewport; a bare document-width check can miss position-fixed
        // or overflow-hidden content.
        for (const locator of [
          page.getByRole("link", {name: "example"}),
          page.getByRole("link", {name: "Appearance"}),
        ]) {
          const bounds = await locator.boundingBox();
          assert.ok(bounds && bounds.width > 0 && bounds.x >= -1
            && bounds.x + bounds.width <= width + 1,
            "Interactive link is outside " + width + "px layout");
        }
        await page.screenshot({path: path.join(evidenceDir, name + "-home-" + width + ".png")});
      }

      await assertSampledTextContrast(page, "light", [
        {foreground: ".brand", background: "header"},
        {foreground: ".hero h1", background: ".hero"},
        {foreground: ".hero p", background: ".hero"},
        {foreground: ".hero .eyebrow", background: ".hero"},
        {foreground: ".card h2 a", background: ".card"},
        {foreground: ".card .muted", background: ".card"},
        {foreground: "footer", background: "body"},
      ]);
      await auditWithAvailableAxe(page, name, "home", evidenceDir);

      // Real Chromium forced-colors media rendering. System color names are
      // expected to resolve to platform colors; focus/underlines must remain
      // discoverable even if the browser overrides author background colors.
      await page.setViewportSize({width: 375, height: 812});
      await page.emulateMedia({forcedColors: "active", colorScheme: "light"});
      assert.equal(await page.evaluate(
        () => matchMedia("(forced-colors: active)").matches), true);
      assert.equal(await page.getByRole("link", {name: "example"}).isVisible(), true);
      assert.equal(await page.getByRole("link", {name: "example"})
        .evaluate((el) => getComputedStyle(el).textDecorationLine.includes("underline")), true);
      await page.getByRole("link", {name: "example"}).focus();
      const focusedOutline = await page.getByRole("link", {name: "example"})
        .evaluate((el) => getComputedStyle(el).outlineStyle);
      assert.equal(focusedOutline, "solid", "Forced-colors focus ring must remain visible.");
      await page.screenshot({
        path: path.join(evidenceDir, name + "-home-forced-colors.png"),
      });
      await page.emulateMedia({forcedColors: "none", colorScheme: "light"});
      assert.equal(await page.evaluate(
        () => matchMedia("(forced-colors: active)").matches), false);

      // Dynamic CSS root-text enlargement is a real rendered-browser
      // stress case, but NOT the browser's native page-zoom control.
      // Test 200% and 400% separately at adequate CSS viewport widths.
      for (const [scale, viewportWidth] of [[2, 640], [4, 1280]]) {
        await page.setViewportSize({width: viewportWidth, height: 900});
        const measured = await page.evaluate((amount) => {
          document.documentElement.style.fontSize = String(amount * 100) + "%";
          return {
            bodyFontPx: parseFloat(getComputedStyle(document.body).fontSize),
            overflowPx: Math.max(document.documentElement.scrollWidth,
              document.body.scrollWidth) - document.documentElement.clientWidth,
          };
        }, scale);
        assert.ok(Math.abs(measured.bodyFontPx - 16 * scale) < 1,
          "Body text did not scale with the root font size at " + scale + "x.");
        assert.ok(measured.overflowPx <= 1,
          "Text-scale horizontal overflow at " + scale + "x: " + measured.overflowPx);
        assert.equal(await page.getByRole("heading", {name: "Private repositories"}).isVisible(), true);
        await page.screenshot({
          path: path.join(evidenceDir, name + "-home-root-text-" + scale + "x.png"),
        });
      }
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "";
      });
      await page.setViewportSize({width: 375, height: 812});

      await page.getByRole("link", {name: "Appearance"}).click();
      await page.setViewportSize({width: 320, height: 812});
      const narrowSettings = await page.evaluate(() =>
        Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)
        - document.documentElement.clientWidth);
      assert.ok(narrowSettings <= 1, "Settings horizontal overflow at 320px.");
      for (const buttonName of ["Save appearance", "Reset to Light"]) {
        const rect = await page.getByRole("button", {name: buttonName}).boundingBox();
        assert.ok(rect && rect.x >= -1 && rect.x + rect.width <= 321,
          "Settings button clipped at 320px: " + buttonName);
      }
      await page.screenshot({
        path: path.join(evidenceDir, name + "-appearance-320.png"),
      });
      await page.setViewportSize({width: 1440, height: 900});
      assert.equal(await page.getByRole("radio", {name: "Light"}).isChecked(), true);
      await page.getByRole("radio", {name: "Dark"}).check();
      const suppliedCsrf = await page.locator("form.card input[name=csrf]").inputValue();
      const expectedCsrf = crypto.createHmac("sha256", token)
        .update("gcgit:appearance:v1").digest("hex");
      assert.equal(suppliedCsrf, expectedCsrf, "Rendered appearance CSRF is token-bound.");
      const malicious = await context.request.post(url + "settings/appearance", {
        headers: {
          Authorization: "Basic " + Buffer.from("owner:" + token).toString("base64"),
          Origin: "https://attacker.invalid",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        data: "mode=dark&csrf=" + expectedCsrf,
      });
      assert.equal(malicious.status(), 403, "Cross-origin POST must fail with valid CSRF.");
      const save = page.getByRole("button", {name: "Save appearance"});
      const height = await save.evaluate((el) => Math.round(el.getBoundingClientRect().height));
      assert.ok(height >= 44, "Save button is smaller than 44px: " + height);
      await save.click();
      await page.waitForLoadState("load");
      assert.equal(await page.locator("html").getAttribute("data-gc-mode"), "dark");
      await page.screenshot({path: path.join(evidenceDir, name + "-appearance-dark.png")});
      await assertSampledTextContrast(page, "dark", [
        {foreground: ".brand", background: "header"},
        {foreground: ".hero h1", background: ".hero"},
        {foreground: ".hero p", background: ".hero"},
        {foreground: ".card legend", background: ".card"},
        {foreground: ".choice", background: ".choice"},
        {foreground: "button", background: "button"},
        {foreground: "footer", background: "body"},
      ]);
      await auditWithAvailableAxe(page, name, "appearance-dark", evidenceDir);
      await page.reload();
      assert.equal(await page.locator("html").getAttribute("data-gc-mode"), "dark");
      await page.getByRole("button", {name: "Reset to Light"}).click();
      assert.equal(await page.locator("html").getAttribute("data-gc-mode"), "light");
      await page.getByRole("radio", {name: "Follow system"}).check();
      await page.getByRole("button", {name: "Save appearance"}).click();
      assert.equal(await page.locator("html").getAttribute("data-gc-mode"), "auto");
      await page.emulateMedia({colorScheme: "dark"});
      const color = await page.locator("html").evaluate((el) =>
        getComputedStyle(el).getPropertyValue("--gc-v1-color-canvas").trim());
      assert.equal(color.toUpperCase(), "#10131E");
      assert.deepEqual(errors, [], "No runtime page errors");
      assert.deepEqual(externalRequests, [], "No external network requests");
      console.log("PASS " + name + " " + browser.version()
        + ": owner authentication, native Git history, keyboard skip link,"
        + " 320/375/640/768/1440 reflow, forced colors, 2x/4x root text,"
        + " scoped contrast and optional axe, Light/Dark/Auto/reset.");
    } finally {
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

async function main() {
  requireOfflineNamespace();
  const pw = require("playwright");
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "gcgit-browser-"));
  fs.chmodSync(temp, 0o700);
  const evidence = process.env.GCGIT_BROWSER_EVIDENCE;
  if (!evidence || !path.isAbsolute(evidence)
      || !fs.statSync(evidence).isDirectory()) {
    throw new Error("GCGIT_BROWSER_EVIDENCE must name the disposable evidence directory.");
  }
  const root = path.join(temp, "private");
  const work = path.join(temp, "work");
  const python = "/usr/bin/python3";
  const env = {
    ...process.env, PYTHONPATH: path.resolve(__dirname, "..", "src"),
    HOME: temp, GIT_CONFIG_NOSYSTEM: "1",
  };
  let server;
  try {
    command(python, ["-m", "goreecloud_git.cli", "--root", root, "init"], env);
    command(python, ["-m", "goreecloud_git.cli", "--root", root, "create", "example"], env);
    command(python, ["-m", "goreecloud_git.cli", "--root", root, "create", "second"], env);
    command("git", ["init", "-b", "main", work], env);
    fs.writeFileSync(path.join(work, "fixture.txt"), "Private browser fixture\n");
    command("git", ["-C", work, "add", "fixture.txt"], env);
    command("git", ["-C", work, "-c", "user.name=Fixture",
      "-c", "user.email=fixture@example.invalid", "commit",
      "-m", "Browser synthetic commit"], env);
    command("git", ["-C", work, "push", path.join(root, "repos", "example.git"), "main"], env);
    const raw = command(python,
      ["-m", "goreecloud_git.cli", "--root", root, "web-token"], env);
    const match = raw.match(/^New web token \(copy now; do not share\): (\S+)$/);
    if (!match) throw new Error("Disposable token generation failed.");
    const token = match[1];
    const port = await availablePort();
    server = spawn(python, ["-m", "goreecloud_git.cli", "--root", root,
      "serve-web", "--port", String(port)], {
      env, cwd: path.resolve(__dirname, ".."), stdio: "ignore",
    });
    const url = "http://127.0.0.1:" + port + "/";
    await waitUntilReady(url, token, server);
    // Firefox may be exercised separately on a suitable supported host.
    // A previously cached Firefox build did not finish initialization in this
    // restricted namespace, so the baseline acceptance covers Chromium only.
    const engines = process.env.GCGIT_BROWSER_ENGINE === "firefox"
      ? ["firefox"] : ["chromium"];
    for (const engineName of engines) {
      await acceptBrowser(engineName, pw[engineName], url, token, evidence, port);
    }
    console.log("PASS: real-browser UI acceptance completed with synthetic data.");
    console.log("NOT VERIFIED: native 200-400% browser zoom, human assistive technology,"
      + " Firefox/Safari, real mobile OS, production TLS/tunnel or full WCAG.");
  } finally {
    if (server && server.exitCode === null) server.kill("SIGTERM");
    fs.rmSync(temp, {recursive: true, force: true});
  }
}

main().catch((error) => {
  // Avoid printing HTTP Authorization token or environment secrets in logs.
  console.error("FAIL browser acceptance:", String(error.message).slice(0, 600));
  process.exitCode = 1;
});
