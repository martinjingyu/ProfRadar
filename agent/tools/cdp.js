import { setTimeout as delay } from "node:timers/promises";

export async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`GET ${url} failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function discoverBrowserWs(port) {
  const version = await getJson(`http://127.0.0.1:${port}/json/version`);
  if (!version.webSocketDebuggerUrl) {
    throw new Error("Chrome did not expose webSocketDebuggerUrl");
  }
  return version.webSocketDebuggerUrl;
}

export async function discoverPageWs(port) {
  const pages = await getJson(`http://127.0.0.1:${port}/json/list`);
  const page = pages.find((t) => {
    return t.type === "page" && t.webSocketDebuggerUrl && !String(t.url).startsWith("devtools://");
  });
  if (!page) {
    throw new Error("Chrome did not expose a page target");
  }
  return page.webSocketDebuggerUrl;
}

export class CdpConnection {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    this.ws.binaryType = "arraybuffer";
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP WebSocket timeout")), 10000);
      this.ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.ws.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error(`CDP WebSocket failed: ${this.wsUrl}`));
      }, { once: true });
    });

    this.ws.addEventListener("message", async (event) => {
      const msg = JSON.parse(await messageText(event.data));
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(`${msg.error.message || "CDP error"}`));
        else resolve(msg.result ?? null);
        return;
      }
      if (msg.method) this.events.push(msg);
    });
  }

  async close() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.close();
      await delay(50);
    }
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    const payload = { id, method };
    if (params && Object.keys(params).length > 0) payload.params = params;
    if (sessionId) payload.sessionId = sessionId;

    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, 30000);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (err) => {
          clearTimeout(timer);
          reject(err);
        }
      });
    });

    this.ws.send(JSON.stringify(payload));
    return promise;
  }

  waitForEvent(method, sessionId, timeoutMs = 15000) {
    const found = this.events.find((e) => {
      return e.method === method && (!sessionId || e.sessionId === sessionId);
    });
    if (found) return Promise.resolve(found);

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.ws.removeEventListener("message", listener);
        reject(new Error(`Timed out waiting for ${method}`));
      }, timeoutMs);
      const listener = async (event) => {
        const msg = JSON.parse(await messageText(event.data));
        if (msg.method === method && (!sessionId || msg.sessionId === sessionId)) {
          clearTimeout(timer);
          this.ws.removeEventListener("message", listener);
          resolve(msg);
        }
      };
      this.ws.addEventListener("message", listener);
    });
  }
}

async function messageText(data) {
  if (typeof data === "string") return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data).toString("utf8");
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer, data.byteOffset, data.byteLength).toString("utf8");
  if (data && typeof data.text === "function") return data.text();
  return String(data);
}

export async function connectPage(port) {
  const pageWs = await discoverPageWs(port);
  const cdp = new CdpConnection(pageWs);
  await cdp.connect();

  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("DOM.enable");
  await cdp.send("Accessibility.enable");
  await cdp.send("Network.enable");

  return { cdp, sessionId: undefined, targetId: undefined };
}

export async function waitForLoad(cdp, sessionId, timeoutMs = 15000) {
  try {
    await cdp.waitForEvent("Page.loadEventFired", sessionId, timeoutMs);
  } catch {
    // SPA and about:blank navigations may not produce a useful load signal.
  }
}
