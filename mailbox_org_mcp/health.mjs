// Healthcheck: alle Endpunkte, die run.mjs gestartet hat (Hub/Gate auf 8099 und/oder die internen
// Brücken), müssen antworten. run.mjs schreibt die Liste nach /tmp/health.json.
import { readFileSync } from "node:fs";

let urls;
try {
  urls = JSON.parse(readFileSync("/tmp/health.json", "utf8"));
} catch {
  process.exit(1);
}
if (!Array.isArray(urls) || urls.length === 0) process.exit(1);
const ok = await Promise.all(
  urls.map((u) => fetch(u, { signal: AbortSignal.timeout(4000) }).then((r) => r.ok).catch(() => false)),
);
process.exit(ok.every(Boolean) ? 0 : 1);
