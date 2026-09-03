// Fails when a non-English locale defines keys missing from English (typos) and reports coverage.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src/i18n/locales/", import.meta.url).pathname;
const flatten = (obj, prefix = "") =>
  Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? flatten(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
const langs = readdirSync(root);
const en = {};
for (const file of readdirSync(join(root, "en"))) en[file] = new Set(flatten(JSON.parse(readFileSync(join(root, "en", file), "utf8"))));
let failed = false;
for (const lang of langs.filter((l) => l !== "en")) {
  for (const file of Object.keys(en)) {
    let keys = [];
    try { keys = flatten(JSON.parse(readFileSync(join(root, lang, file), "utf8"))); } catch { continue; }
    const extra = keys.filter((k) => !en[file].has(k));
    if (extra.length) { failed = true; console.error(`[${lang}/${file}] unknown keys: ${extra.join(", ")}`); }
    const coverage = Math.round((keys.length / en[file].size) * 100);
    console.log(`${lang}/${file}: ${coverage}% (${keys.length}/${en[file].size})`);
  }
}
process.exit(failed ? 1 : 0);
