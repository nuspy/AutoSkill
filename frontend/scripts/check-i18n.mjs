// Fails when a non-English locale defines keys missing from English (typos) and reports coverage.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src/i18n/locales/", import.meta.url).pathname;
const flatten = (obj, prefix = "") =>
  Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? flatten(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
const REQUIRED_LOCALES = ["it", "de", "hu", "es", "fr"]; // must cover 100% of the English keys
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
    const missing = [...en[file]].filter((k) => !keys.includes(k));
    const coverage = Math.round((keys.length / en[file].size) * 100);
    console.log(`${lang}/${file}: ${coverage}% (${keys.length}/${en[file].size})`);
    if (REQUIRED_LOCALES.includes(lang) && missing.length) {
      failed = true;
      console.error(`[${lang}/${file}] missing keys: ${missing.join(", ")}`);
    }
  }
}
for (const lang of REQUIRED_LOCALES) {
  for (const file of Object.keys(en)) {
    try { readFileSync(join(root, lang, file)); } catch { failed = true; console.error(`[${lang}/${file}] file missing`); }
  }
}
process.exit(failed ? 1 : 0);
