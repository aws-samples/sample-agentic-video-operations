// The web app's only console sink (RB10). Event names, counts and lengths only: never a
// prompt, answer, SQL, query result, chart payload, user or session identity, or an error
// message (which can quote any of them). scripts/tests/test_hydrolix_web_app.py fails on any
// other console call in src/.

const PREFIX = "[hydrolix]";

/** Log one event with numeric or boolean metadata; anything else is dropped. */
export function logEvent(name, metadata = {}) {
  const safe = {};
  for (const [key, value] of Object.entries(metadata)) {
    if (typeof value === "number" || typeof value === "boolean") {
      safe[key] = value;
    }
  }
  console.info(`${PREFIX} ${name}`, safe);
}

/** Log that something failed, naming only the error's class. */
export function logFailure(name, error) {
  const kind = error && typeof error.name === "string" ? error.name : typeof error;
  console.error(`${PREFIX} ${name} failed: ${kind}`);
}
