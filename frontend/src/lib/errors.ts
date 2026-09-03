import type { TFunction } from "i18next";
import { ApiError } from "@/api/client";

export function errorMessage(error: unknown, t: TFunction): string {
  if (error instanceof ApiError) {
    const key = `errors.${error.code}`;
    const translated = t(key, { defaultValue: "" });
    if (translated) return translated;
    if (error.status === 403) return t("errors.forbidden");
    if (error.status === 404) return t("errors.not_found");
    if (error.status === 422) return t("errors.validation_failed");
  }
  return t("errors.generic");
}
