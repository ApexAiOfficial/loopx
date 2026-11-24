#!/usr/bin/env node
// An open tab imports an as-yet-unloaded module after its server is upgraded.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { resolve } from "node:path";
import { launchBrowser, loadPlaywright } from "./dashboard-browser-smoke-support.mjs";
import { resolveTestPython } from "../scripts/test-python.mjs";

const python = String.raw`
import importlib.util, json, sys, tempfile, threading
from pathlib import Path
from loopx.chat_server import ChatHTTPServer, ChatRequestHandler
spec = importlib.util.spec_from_file_location("builder", "scripts/chat_bundle.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
with tempfile.TemporaryDirectory(prefix="loopx-tab-upgrade-") as temporary:
    builder.ROOT = Path(temporary)
    builder.OUTPUT = Path(temporary) / "chat"
    def deliver(name):
        with tempfile.TemporaryDirectory(dir=temporary) as work:
            stage = Path(work) / "chat"
            (stage / "assets").mkdir(parents=True)
            (stage / "assets" / (name + ".js")).write_text("export const version = '" + name + "'")
            (stage / "assets" / (name + ".css")).write_text("body { color: black }")
            (stage / "manifest.webmanifest").write_text("{}")
            (stage / "index.html").write_text('<link rel="stylesheet" href="/chat/assets/' + name + '.css"><button onclick="import(\'/chat/assets/' + name + '.js\').then(m => document.querySelector(\'output\').textContent=m.version)">Load module</button><output></output>')
            current = ["assets/" + name + ".css", "assets/" + name + ".js"]
            builder.finish_delivery(stage, builder.OUTPUT if builder.OUTPUT.exists() else None, current, {}, "a" * 40)
    deliver("one")
    server = ChatHTTPServer(("127.0.0.1", 0), ChatRequestHandler)
    server.assets_dir = builder.OUTPUT
    server.verbose = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        for line in sys.stdin:
            deliver(line.strip())
            print(json.dumps({"delivered": line.strip()}), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
`;
const child = spawn(resolveTestPython(), ["-u", "-c", python], {
  cwd: resolve(import.meta.dirname, ".."), stdio: ["pipe", "pipe", "inherit"],
});
const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
async function read() {
  const result = await Promise.race([
    lines.next(), new Promise((_, reject) => { const t = setTimeout(() => reject(new Error("upgrade server timeout")), 30000); t.unref(); }),
  ]);
  assert.equal(result.done, false, "upgrade server exited");
  return JSON.parse(result.value);
}
let browser;
try {
  const { port } = await read();
  browser = await launchBrowser(loadPlaywright().chromium);
  const oldTab = await browser.newPage();
  const url = `http://127.0.0.1:${port}/chat/`;
  await oldTab.goto(url);
  child.stdin.write("two\n");
  assert.equal((await read()).delivered, "two");
  await oldTab.getByRole("button").click();
  await oldTab.waitForFunction(() => document.querySelector("output").textContent === "one");
  const newTab = await browser.newPage();
  await newTab.goto(url);
  await newTab.getByRole("button").click();
  await newTab.waitForFunction(() => document.querySelector("output").textContent === "two");
  child.stdin.write("three\n");
  assert.equal((await read()).delivered, "three");
  assert.equal((await newTab.request.get(`${url}assets/two.js`)).status(), 200);
  assert.equal((await newTab.request.get(`${url}assets/one.js`)).status(), 404);
  console.log("PASS: old tab lazy import after upgrade; current tab renders; history bounded to one previous delivery");
} finally {
  await browser?.close();
  child.stdin.end();
  child.kill();
}
