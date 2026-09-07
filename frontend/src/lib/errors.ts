import type { TFunction } from "i18next";
import { ApiError } from "@/api/client";

/**
 * Turn an API failure into a sentence a person can read.
 *
 * Every key is namespaced to `common` on purpose. The error strings live only there, while most
 * callers hold a `t` from `useTranslation(["skills", "common"])` — whose *default* namespace is
 * `skills`. An unqualified `errors.not_found` therefore resolved against a namespace that has no
 * `errors` section at all, and i18next then does what it always does with a miss: it returns the key.
 * So a person clicking a button got the literal string `errors.not_found` instead of an explanation,
 * everywhere in the app that error came from a page whose first namespace was not `common`.
 */
export function errorMessage(error: unknown, t: TFunction): string {
  if (error instanceof ApiError) {
    const translated = t(`common:errors.${error.code}`, { defaultValue: "" });
    if (translated) return translated;
    if (error.status === 403) return t("common:errors.forbidden");
    if (error.status === 404) return t("common:errors.not_found");
    if (error.status === 422) return t("common:errors.validation_failed");
  }
  return t("common:errors.generic");
}
