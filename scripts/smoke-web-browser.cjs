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

      const widths = [375, 768, 1440];
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
        await page.screenshot({path: path.join(evidenceDir, name + "-home-" + width + ".png")});
      }

      await page.getByRole("link", {name: "Appearance"}).click();
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
        + ": private HTTP auth, real native Git history, skip-link keyboard,"
        + " 375/768/1440 reflow, 44px control, light/dark/auto and reset.");
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
    console.log("NOT VERIFIED: screen reader, mobile OS, production TLS/tunnel, full WCAG.");
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
