#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { connectPage, discoverBrowserWs, waitForLoad } from "./cdp.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// stateDir: per-process (PID-based) — stores refs.json and session.json.
// Isolates parallel runs from clobbering each other's snapshot state.
const _stateSlot = process.env.AGENT_BROWSER_INSTANCE || "default";
const stateDir = join(root, ".agentbrowser", _stateSlot);
const statePath = join(stateDir, "session.json");
const refsPath = join(stateDir, "refs.json");

// profileDir: per-candidate (stable across runs) — stores cookies, login sessions.
// Reusing the same profile lets the agent skip CAPTCHA/login on repeat runs.
const _profileSlot = process.env.AGENT_BROWSER_PROFILE || _stateSlot;
const profileDir = join(root, ".agentbrowser", "profiles", _profileSlot);

const defaultPort = Number(process.env.AGENT_BROWSER_PORT || 9222);

function hasFlag(args, flag) {
  return args.includes(flag);
}

function ensureStateDir() {
  mkdirSync(stateDir, { recursive: true });
}

function readState() {
  if (!existsSync(statePath)) return { port: defaultPort };
  return JSON.parse(readFileSync(statePath, "utf8"));
}

function writeState(state) {
  ensureStateDir();
  writeFileSync(statePath, JSON.stringify(state, null, 2));
}

function updateState(patch) {
  writeState({ ...readState(), ...patch });
}

function chromeCandidates() {
  const local = process.env.LOCALAPPDATA;
  return [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    local && join(local, "Google\\Chrome\\Application\\chrome.exe"),
    local && join(local, "BraveSoftware\\Brave-Browser\\Application\\brave.exe")
  ].filter(Boolean);
}

function findChrome() {
  const found = chromeCandidates().find((p) => existsSync(p));
  if (!found) {
    throw new Error("Chrome not found. Set CHROME_PATH to chrome.exe.");
  }
  return found;
}

function startChrome(chrome, args) {
  if (process.platform === "win32") {
    const child = spawn("cmd.exe", ["/c", "start", '""', chrome, ...args], {
      detached: true,
      stdio: "ignore",
      windowsHide: true
    });
    child.unref();
    return;
  }

  const child = spawn(chrome, args, {
    detached: true,
    stdio: "ignore"
  });
  child.unref();
}

async function isPortReady(port) {
  try {
    await discoverBrowserWs(port);
    return true;
  } catch {
    return false;
  }
}

async function ensureChrome(port = defaultPort, options = {}) {
  if (await isPortReady(port)) {
    writeState({ port, headless: Boolean(options.headless) });
    return;
  }

  ensureStateDir();
  mkdirSync(profileDir, { recursive: true });

  const chrome = findChrome();
  const chromeArgs = [
    `--remote-debugging-port=${port}`,
    "--remote-allow-origins=*",
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    ...(options.headless ? ["--headless=new", "--disable-gpu", "--window-size=1280,720"] : []),
    "about:blank"
  ];
  startChrome(chrome, chromeArgs);

  for (let i = 0; i < 80; i++) {
    if (await isPortReady(port)) {
      writeState({ port, profileDir, headless: Boolean(options.headless) });
      return;
    }
    await delay(250);
  }
  throw new Error(`Chrome started but CDP was not ready on port ${port}`);
}

async function withPage(fn) {
  const state = readState();
  await ensureChrome(state.port ?? defaultPort, { headless: state.headless });
  const { cdp, sessionId } = await connectPage(state.port ?? defaultPort);
  try {
    return await fn(cdp, sessionId);
  } finally {
    await cdp.close();
  }
}

function normalizeUrl(raw) {
  if (/^(https?|about|data|file|chrome):/i.test(raw)) return raw;
  return `https://${raw}`;
}

function jsString(value) {
  return JSON.stringify(value);
}

async function runtimeEval(cdp, sessionId, expression, returnByValue = true) {
  const res = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue
  }, sessionId);
  if (res.exceptionDetails) {
    throw new Error(res.exceptionDetails.text || "Runtime.evaluate failed");
  }
  return res.result?.value;
}

async function cmdOpen(args) {
  if (hasFlag(args, "--headless")) updateState({ headless: true });
  if (hasFlag(args, "--visible")) updateState({ headless: false });
  const firstValue = args.find((arg) => !arg.startsWith("--"));
  const url = normalizeUrl(firstValue ?? "about:blank");
  await withPage(async (cdp, sessionId) => {
    await cdp.send("Page.navigate", { url }, sessionId);
    await waitForLoad(cdp, sessionId);
    console.log(`opened ${url}`);
  });
}

async function cmdSnapshot(args = []) {
  await withPage(async (cdp, sessionId) => {
    const origin = await runtimeEval(cdp, sessionId, "location.href");

    const result = await runtimeEval(cdp, sessionId, `(() => {

      // ── Visible text content ──────────────────────────────────────────
      const contentEl =
        document.querySelector("main, [role=main], article, #content, #main, #app") ||
        document.body;
      const pageText = contentEl.innerText
        .replace(/\\t/g, " ")
        .replace(/\\u00a0/g, " ")
        .replace(/[\\u200b\\u200c\\u200d\\u200e\\u200f\\ufeff\\u00ad\\u2060]/g, "")
        .replace(/[ ]{3,}/g, "  ")
        .replace(/\\n{3,}/g, "\\n\\n")
        .trim();

      // ── Interactive elements ──────────────────────────────────────────
      const isVisible = (el) => {
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.visibility !== "hidden" && s.display !== "none" && r.width > 0 && r.height > 0;
      };
      const selectorFor = (el) => {
        if (el.id) return "#" + CSS.escape(el.id);
        const parts = [];
        let cur = el;
        while (cur && cur.nodeType === 1 && parts.length < 5) {
          let part = cur.localName;
          if (cur.classList && cur.classList.length)
            part += "." + [...cur.classList].slice(0, 2).map(CSS.escape).join(".");
          const parent = cur.parentElement;
          if (parent) {
            const same = [...parent.children].filter(x => x.localName === cur.localName);
            if (same.length > 1) part += \`:nth-of-type(\${same.indexOf(cur) + 1})\`;
          }
          parts.unshift(part);
          cur = parent;
        }
        return parts.join(" > ");
      };

      // Deduplicate links by normalized href to remove repeated nav/footer links
      const seenHrefs = new Set();
      const nodes = [...document.querySelectorAll(
        "a[href],button,input,textarea,select,[role=button],[contenteditable=true]"
      )].filter(el => {
        if (!isVisible(el)) return false;
        if (el.href) {
          let norm = el.href;
          try { norm = new URL(el.href).href; } catch {}
          if (seenHrefs.has(norm)) return false;
          seenHrefs.add(norm);
        }
        return true;
      });

      const refs = {};
      const lines = nodes.flatMap((el, i) => {
        const ref = "e" + (i + 1);
        const tag = el.localName;
        const href = el.href || "";
        const label = (el.innerText || el.value || el.placeholder || el.ariaLabel || el.title || href || "")
          .replace(/\\s+/g, " ").trim().slice(0, 80);
        if (!label) return [];
        const r = el.getBoundingClientRect();
        const role = tag === "a" ? "link"
          : (tag === "button" || el.getAttribute("role") === "button") ? "btn"
          : "input";

        refs[ref] = {
          role,
          name: label,
          selector: selectorFor(el),
          x: Math.round(r.left + r.width / 2),
          y: Math.round(r.top + r.height / 2),
          ...(href ? { url: href } : {}),
        };

        if (href)  return [\`@\${ref} [link] "\${label}" → \${href}\`];
        if (role === "btn") return [\`@\${ref} [btn] "\${label}"\`];
        const ph = el.placeholder || el.name || el.getAttribute("type") || "";
        return [\`@\${ref} [input] "\${ph}"\`];
      });

      return { pageText, elemLines: lines, refs };
    })()`);

    ensureStateDir();
    writeFileSync(refsPath, JSON.stringify(result.refs, null, 2));

    const textBlock = result.pageText
      ? `[TEXT]\n${result.pageText}\n[/TEXT]`
      : "[TEXT](empty)[/TEXT]";
    const elemBlock = result.elemLines.length
      ? `[ELEMENTS]\n${result.elemLines.join("\n")}\n[/ELEMENTS]`
      : "[ELEMENTS](none)[/ELEMENTS]";

    const snapshot = `[URL: ${origin}]\n\n${textBlock}\n\n${elemBlock}`;

    if (args.includes("--json")) {
      console.log(JSON.stringify({ snapshot, origin, refs: result.refs }, null, 2));
      return;
    }
    console.log(snapshot);
  });
}

function readRefs() {
  if (!existsSync(refsPath)) {
    throw new Error("No refs saved. Run `node src/cli.js snapshot` first.");
  }
  const refs = JSON.parse(readFileSync(refsPath, "utf8"));
  if (Array.isArray(refs)) return refs;
  return Object.entries(refs).map(([ref, entry]) => ({ ref, ...entry }));
}

async function waitForNavigation(cdp, sessionId) {
  // If a navigation was triggered by the click, wait for it to finish.
  // If no frame navigation starts within 1s, assume non-navigation click and return.
  let navigated = false;
  try {
    await cdp.waitForEvent("Page.frameNavigated", sessionId, 1000);
    navigated = true;
  } catch {}
  if (navigated) {
    await waitForLoad(cdp, sessionId, 15000);
  } else {
    // Give JS event handlers time to run (e.g. AJAX, dropdown open, state update).
    await delay(300);
  }
}

async function cmdClick(args) {
  const target = args[0];
  if (!target) throw new Error("Usage: click <@ref|css-selector|x,y>");

  await withPage(async (cdp, sessionId) => {
    // Prevent links from opening new tabs
    await runtimeEval(cdp, sessionId,
      `document.querySelectorAll('[target]').forEach(el => el.removeAttribute('target'));` +
      `window.open = (url) => { if (url) window.location.href = url; return null; };`
    ).catch(() => {});

    if (/^@\w+/.test(target)) {
      const id = target.slice(1);
      const ref = readRefs().find((r) => r.ref === id || r.ref === target);
      if (!ref) throw new Error(`Unknown ref ${target}. Run snapshot again.`);

      // Prefer JS el.click() via selector — works for React/Vue synthetic events
      // and doesn't depend on viewport coordinates being current.
      if (ref.selector) {
        try {
          await runtimeEval(cdp, sessionId, `(() => {
            const el = document.querySelector(${jsString(ref.selector)});
            if (!el) throw new Error("selector not found: " + ${jsString(ref.selector)});
            el.scrollIntoView({ block: "center", inline: "nearest" });
            el.click();
            return true;
          })()`);
          await waitForNavigation(cdp, sessionId);
          console.log(`clicked ${target} via selector`);
          return;
        } catch {}
      }

      // Fallback: raw mouse events at stored viewport coordinates.
      await cdp.send("Input.dispatchMouseEvent", {
        type: "mousePressed", x: ref.x, y: ref.y, button: "left", clickCount: 1
      }, sessionId);
      await cdp.send("Input.dispatchMouseEvent", {
        type: "mouseReleased", x: ref.x, y: ref.y, button: "left", clickCount: 1
      }, sessionId);
      await waitForNavigation(cdp, sessionId);
      console.log(`clicked ${target} via mouse event`);
      return;
    }

    const xy = target.match(/^(\d+),(\d+)$/);
    if (xy) {
      const x = Number(xy[1]);
      const y = Number(xy[2]);
      await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 }, sessionId);
      await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 }, sessionId);
      await waitForNavigation(cdp, sessionId);
      console.log(`clicked ${x},${y}`);
      return;
    }

    await runtimeEval(cdp, sessionId, `(() => {
      const el = document.querySelector(${jsString(target)});
      if (!el) throw new Error("selector not found: " + ${jsString(target)});
      el.scrollIntoView({ block: "center", inline: "center" });
      el.click();
      return true;
    })()`);
    await waitForNavigation(cdp, sessionId);
    console.log(`clicked ${target}`);
  });
}

async function cmdScreenshot(args) {
  const out = resolve(args[0] ?? join(stateDir, `screenshot-${Date.now()}.png`));
  await withPage(async (cdp, sessionId) => {
    const res = await cdp.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true
    }, sessionId);
    writeFileSync(out, Buffer.from(res.data, "base64"));
    console.log(out);
  });
}

async function cmdScroll(args) {
  let amount;
  const direction = args[0]?.toLowerCase();
  if (direction === "up" || direction === "down") {
    const pixels = Number(args[1] ?? 600);
    if (!Number.isFinite(pixels)) {
      throw new Error("Usage: scroll up [pixels] | scroll down [pixels]");
    }
    amount = direction === "up" ? -Math.abs(pixels) : Math.abs(pixels);
  } else {
    amount = Number(args[0] ?? 600);
    if (!Number.isFinite(amount)) {
      throw new Error("Usage: scroll [pixels] | scroll up [pixels] | scroll down [pixels]");
    }
  }

  await withPage(async (cdp, sessionId) => {
    await cdp.send("Input.dispatchMouseEvent", {
      type: "mouseWheel",
      x: 500,
      y: 500,
      deltaX: 0,
      deltaY: amount
    }, sessionId);
    console.log(amount < 0 ? `scrolled up ${Math.abs(amount)}` : `scrolled down ${amount}`);
  });
}

async function cmdKeyboard(args) {
  const sub = args[0];
  if (sub === "type") {
    const text = args.slice(1).join(" ");
    if (!text) throw new Error("Usage: keyboard type <text>");
    await withPage(async (cdp, sessionId) => {
      await cdp.send("Input.insertText", { text }, sessionId);
      console.log(`typed ${text.length} chars`);
    });
    return;
  }

  if (sub === "press") {
    const key = args[1];
    if (!key) throw new Error("Usage: keyboard press <Enter|Tab|Escape|...>");
    await withPage(async (cdp, sessionId) => {
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key, code: key }, sessionId);
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key, code: key }, sessionId);
      console.log(`pressed ${key}`);
    });
    return;
  }

  throw new Error("Usage: keyboard type <text> | keyboard press <key>");
}

async function cmdClose() {
  const state = readState();
  const port = state.port ?? defaultPort;
  try {
    await ensureChrome(port);
    const { cdp } = await connectPage(port);
    await cdp.send("Browser.close").catch(() => {});
    await cdp.close().catch(() => {});
    console.log(`Chrome on port ${port} closed`);
  } catch {
    // Chrome may already be gone — not an error
    console.log(`Chrome on port ${port} was not running`);
  }
}

function usage() {
  console.log(`agentBrowser minimal CDP controller

Commands:
  node src/cli.js start [port] [--headless] launch Chrome
  node src/cli.js open <url>                navigate current tab
  node src/cli.js snapshot                  list interactive elements as @e refs
  node src/cli.js click <@ref|selector|x,y>  click element
  node src/cli.js screenshot [path]         save PNG screenshot
  node src/cli.js scroll [pixels]           scroll by signed pixels
  node src/cli.js scroll down [pixels]      scroll down
  node src/cli.js scroll up [pixels]        scroll up
  node src/cli.js keyboard type <text>      type text
  node src/cli.js keyboard press <key>      press key
`);
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  if (!cmd || cmd === "help" || cmd === "--help") return usage();

  if (cmd === "start") {
    const headless = hasFlag(args, "--headless");
    const portArg = args.find((arg) => !arg.startsWith("--"));
    const port = Number(portArg ?? defaultPort);
    await ensureChrome(port, { headless });
    console.log(`${headless ? "headless" : "visible"} Chrome ready on CDP port ${port}`);
    return;
  }
  if (cmd === "open") return cmdOpen(args);
  if (cmd === "snapshot") return cmdSnapshot(args);
  if (cmd === "click") return cmdClick(args);
  if (cmd === "screenshot") return cmdScreenshot(args);
  if (cmd === "scroll") return cmdScroll(args);
  if (cmd === "keyboard") return cmdKeyboard(args);
  if (cmd === "close") return cmdClose();

  throw new Error(`Unknown command: ${cmd}`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
