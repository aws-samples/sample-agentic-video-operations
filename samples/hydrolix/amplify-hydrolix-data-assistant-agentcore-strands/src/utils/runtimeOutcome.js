// What a request ended with (T41). The runtime's last record is always the request's
// {"query_results": [...]}, after any {"error": ...}: so note both while the stream is read,
// and decide only once it has ended. Throwing on the error would lose the queries that ran.
export const createRuntimeOutcome = () => {
  let error = null;
  let queryResults = [];
  return {
    // True when the record was an outcome record, so the caller has nothing else to do.
    take(record) {
      if (Array.isArray(record.query_results)) {
        queryResults = record.query_results;
        return true;
      }
      if (typeof record.error === "string") {
        error = error ?? record.error; // the first error is the cause
        return true;
      }
      return false;
    },
    get error() {
      return error;
    },
    get queryResults() {
      return queryResults;
    },
  };
};
