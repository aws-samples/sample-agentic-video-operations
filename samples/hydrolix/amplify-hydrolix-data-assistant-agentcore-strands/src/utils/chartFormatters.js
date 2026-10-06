// Chart formatters by name (RB11). The chart model is prompted with CDN data that callers
// partly control (URLs, user agents, referrers), so its output is never evaluated as code.
// It may only name one of these formatters; any other "formatter" value is removed and
// counted. No imports, so scripts/tests/web can load this module from source.

const toNumber = (value) => (typeof value === "number" ? value : Number(value));

const fixed = (value, digits) => {
  const number = toNumber(value);
  return Number.isFinite(number) ? number.toFixed(digits) : String(value);
};

// The category label ApexCharts passes alongside a value (pies: seriesIndex; bars and
// funnels: dataPointIndex).
const labelOf = (options) => {
  const w = options && options.w;
  if (!w) {
    return "";
  }
  const index =
    typeof options.dataPointIndex === "number" && options.dataPointIndex >= 0
      ? options.dataPointIndex
      : options.seriesIndex;
  const labels = (w.config && w.config.labels && w.config.labels.length
    ? w.config.labels
    : w.globals && w.globals.labels) || [];
  const label = labels[index];
  return label === undefined || label === null ? "" : String(label);
};

export const CHART_FORMATTERS = Object.freeze({
  fixed2: (value) => fixed(value, 2),
  integer: (value) => fixed(value, 0),
  percent: (value) => `${fixed(value, 2)}%`,
  currency: (value) => `$${fixed(value, 2)}`,
  label_and_value: (value, options) => `${labelOf(options)}: ${value}`,
  label_and_percent: (value, options) => `${labelOf(options)}: ${fixed(value, 2)}%`,
});

export const CHART_FORMATTER_NAMES = Object.freeze(Object.keys(CHART_FORMATTERS));

/**
 * Replace every "formatter" naming an allowlisted formatter with our implementation, and
 * remove every other "formatter" (a function string, an unknown name, a non-string).
 * Returns a new configuration and how many formatters were dropped; nothing is executed.
 */
export function applyChartFormatters(configuration) {
  let dropped = 0;
  const walk = (value) => {
    if (Array.isArray(value)) {
      return value.map(walk);
    }
    if (value === null || typeof value !== "object") {
      return value;
    }
    const copy = {};
    for (const [key, item] of Object.entries(value)) {
      if (key !== "formatter") {
        copy[key] = walk(item);
      } else if (
        typeof item === "string" &&
        Object.prototype.hasOwnProperty.call(CHART_FORMATTERS, item)
      ) {
        copy[key] = CHART_FORMATTERS[item];
      } else {
        dropped += 1;
      }
    }
    return copy;
  };
  return { configuration: walk(configuration), dropped };
}
