// node --test: the web app keeps the queries a request ran even when it ends in an error (T41).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const SRC = new URL(
  "../../../samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands/src/utils/",
  import.meta.url,
);
const { createRuntimeOutcome } = await import(
  `data:text/javascript,${encodeURIComponent(await readFile(new URL("runtimeOutcome.js", SRC), "utf8"))}`
);

const read = (records) => {
  const outcome = createRuntimeOutcome();
  const rest = records.filter((record) => !outcome.take(record));
  return { outcome, rest };
};

test("an error before the final query records keeps both", () => {
  const query = { query: "SELECT 1 FROM video.cmcd", status: "success" };
  const { outcome, rest } = read([
    { data: "Partial answer. " },
    { error: "The assistant stopped: this request reached its 180-second limit." },
    { query_results: [query] },
  ]);
  assert.deepEqual(outcome.queryResults, [query]);
  assert.match(outcome.error, /stopped/);
  assert.deepEqual(rest, [{ data: "Partial answer. " }]);
});

test("a successful request has records and no error", () => {
  const { outcome } = read([{ data: "42" }, { query_results: [] }]);
  assert.equal(outcome.error, null);
  assert.deepEqual(outcome.queryResults, []);
});

test("the first error is the one reported", () => {
  const { outcome } = read([{ error: "first" }, { error: "second" }, { query_results: [] }]);
  assert.equal(outcome.error, "first");
});
