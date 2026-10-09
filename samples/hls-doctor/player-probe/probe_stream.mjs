// Headless hls.js session over one manifest URL; JSON report on stdout.
//
// Usage: node probe_stream.mjs <manifest-url> [duration-seconds]
// Needs `npm install` in this directory and a Chromium playwright-core can drive.

import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { chromium } from "playwright-core";

const require = createRequire(import.meta.url);
const hlsJsPath = require.resolve("hls.js/dist/hls.min.js");

const url = process.argv[2];
const durationSeconds = Number(process.argv[3] ?? 10);
if (!url) {
  console.error("usage: node probe_stream.mjs <manifest-url> [duration-seconds]");
  process.exit(2);
}

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage();
const report = { url, events: [], errors: [], requests: [] };

page.on("request", (request) =>
  report.requests.push({ url: request.url(), method: request.method() })
);
page.on("response", (response) => {
  const match = report.requests.find((r) => r.url === response.url() && !r.status);
  if (match) match.status = response.status();
});

await page.setContent('<video id="v" muted autoplay></video>');
await page.addScriptTag({ content: readFileSync(hlsJsPath, "utf8") });
await page.evaluate(
  ([manifestUrl]) => {
    window.__events = [];
    const hls = new window.Hls({ enableWorker: false });
    const record = (name) => (eventName, data) =>
      window.__events.push({
        name,
        details: data?.details ?? null,
        fatal: data?.fatal ?? null,
        level: data?.level ?? null,
      });
    for (const name of [
      "MANIFEST_LOADED", "LEVEL_SWITCHED", "FRAG_BUFFERED", "FRAG_CHANGED",
      "AUDIO_TRACK_SWITCHED", "SUBTITLE_TRACK_SWITCH", "ERROR", "BUFFER_STALLED_ERROR",
    ]) {
      if (window.Hls.Events[name]) hls.on(window.Hls.Events[name], record(name));
    }
    hls.loadSource(manifestUrl);
    hls.attachMedia(document.getElementById("v"));
  },
  [url]
);

await page.waitForTimeout(durationSeconds * 1000);
const events = await page.evaluate(() => window.__events);
report.events = events.filter((event) => event.name !== "ERROR");
report.errors = events.filter((event) => event.name === "ERROR");
await browser.close();
console.log(JSON.stringify(report));
