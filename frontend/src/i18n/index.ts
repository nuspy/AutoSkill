import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

const modules = import.meta.glob("./locales/*/*.json", { eager: true }) as Record<string, { default: Record<string, unknown> }>;

const resources: Record<string, Record<string, Record<string, unknown>>> = {};
for (const [path, mod] of Object.entries(modules)) {
  const match = path.match(/locales\/([a-z]{2})\/([a-z]+)\.json$/);
  if (!match) continue;
  const [, lang, ns] = match;
  resources[lang] ??= {};
  resources[lang][ns] = mod.default;
}

export const SUPPORTED_LOCALES = ["en", "it", "hu", "de", "es", "fr"] as const;
export const LOCALE_NAMES: Record<string, string> = {
  en: "English", it: "Italiano", hu: "Magyar", de: "Deutsch", es: "Español", fr: "Français",
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "en",
    supportedLngs: [...SUPPORTED_LOCALES],
    ns: ["common", "auth", "projects", "admin", "me"],
    defaultNS: "common",
    interpolation: { escapeValue: false },
    detection: { order: ["localStorage", "navigator"], lookupLocalStorage: "autoskill.locale", caches: ["localStorage"] },
  });

export default i18n;
