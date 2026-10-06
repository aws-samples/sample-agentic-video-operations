// The AgentCore runtime streams Server-Sent Events: one `data: <JSON string>` record per
// event, records separated by a blank line. fetch() hands over arbitrary byte chunks, so a
// record (or one UTF-8 character) can be split across reads. This parser buffers across
// chunks and returns only complete records; end() flushes the last one.

const RECORD_SEPARATOR = /\r?\n\r?\n/;

/** The text the runtime yielded for one record, or null when it has no data line. */
export function readRecord(record) {
  const data = record
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""))
    .join("\n");
  if (!data) {
    return null;
  }
  const value = JSON.parse(data);
  return typeof value === "string" ? value : JSON.stringify(value);
}

export function createSseParser() {
  const decoder = new TextDecoder("utf-8");
  let pending = "";

  const complete = (final) => {
    const records = pending.split(RECORD_SEPARATOR);
    pending = final ? "" : records.pop();
    return records.filter((record) => record.trim()).map(readRecord).filter((t) => t !== null);
  };

  return {
    /** Feed one chunk of bytes; returns the texts of the records it completed. */
    push(bytes) {
      pending += decoder.decode(bytes, { stream: true });
      return complete(false);
    },
    /** The stream ended: return the last record, if any. */
    end() {
      pending += decoder.decode();
      return complete(true);
    },
  };
}
