// node --test: the Hydrolix web app's pure stream parser and logger.
// Modules are loaded from source as ES modules, so this runs on any Node with node:test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const SRC = new URL(
  "../../../samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands/src/utils/",
  import.meta.url,
);
const load = async (name) =>
  import(`data:text/javascript,${encodeURIComponent(await readFile(new URL(name, SRC), "utf8"))}`);

// What the runtime sends: each yielded string, JSON-encoded once more by the SDK.
const record = (yielded) => `data: ${JSON.stringify(yielded)}\n\n`;
const ANSWER = JSON.stringify({ data: "Cache hit rate is 94 % — POP fra-1 needs attention ✅" }) + "\n";
const TOOL = JSON.stringify({ event: { contentBlockStop: {} } }) + "\n";
const STREAM = new TextEncoder().encode(record(TOOL) + record(ANSWER) + record(TOOL));

const parseInChunks = async (cuts) => {
  const { createSseParser } = await load("sseRecords.js");
  const parser = createSseParser();
  const texts = [];
  let start = 0;
  for (const cut of [...cuts, STREAM.length]) {
    texts.push(...parser.push(STREAM.slice(start, cut)));
    start = cut;
  }
  texts.push(...parser.end());
  return texts;
};

test("one read with every record gives every record", async () => {
  assert.deepEqual(await parseInChunks([]), [TOOL, ANSWER, TOOL]);
});

test("a record split at every byte boundary is never dropped", async () => {
  for (let cut = 1; cut < STREAM.length; cut += 1) {
    assert.deepEqual(await parseInChunks([cut]), [TOOL, ANSWER, TOOL], `cut at byte ${cut}`);
  }
});

test("a record split across three reads, inside multi-byte characters, survives", async () => {
  const text = new TextDecoder().decode(STREAM);
  const euro = new TextEncoder().encode(text.slice(0, text.indexOf("—"))).length + 1; // mid "—"
  const check = new TextEncoder().encode(text.slice(0, text.indexOf("✅"))).length + 2; // mid "✅"
  assert.deepEqual(await parseInChunks([euro, check]), [TOOL, ANSWER, TOOL]);
});

test("a final record without its blank line is flushed at the end", async () => {
  const { createSseParser } = await load("sseRecords.js");
  const parser = createSseParser();
  const unterminated = new TextEncoder().encode(record(ANSWER).trimEnd());
  assert.deepEqual(parser.push(unterminated), []);
  assert.deepEqual(parser.end(), [ANSWER]);
});

test("the logger keeps numbers and booleans and drops every string", async () => {
  const { logEvent, logFailure } = await load("logMetadata.js");
  const seen = [];
  const original = { info: console.info, error: console.error };
  console.info = (...args) => seen.push(args);
  console.error = (...args) => seen.push(args);
  try {
    logEvent("runtime stream ended", { records: 3, ok: true, answer: "SECRET-ANSWER", sub: "user-1" });
    logFailure("ask the assistant", new TypeError("SECRET-PROMPT leaked in a message"));
  } finally {
    Object.assign(console, original);
  }
  assert.deepEqual(seen[0], ["[hydrolix] runtime stream ended", { records: 3, ok: true }]);
  assert.deepEqual(seen[1], ["[hydrolix] ask the assistant failed: TypeError"]);
  assert.ok(!JSON.stringify(seen).includes("SECRET"));
});
