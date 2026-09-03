import { request, type FullConfig } from "@playwright/test";

export const ADMIN = { email: "admin@example.com", password: "password123", name: "E2E Admin" };

/** The very first account of the fresh e2e database becomes the administrator: create it before any test. */
export default async function globalSetup(config: FullConfig) {
  const base = (config.projects[0].use.baseURL as string).replace(/\/$/, "");
  const ctx = await request.newContext({ baseURL: base });
  const res = await ctx.post("/api/v1/auth/register", { data: { email: ADMIN.email, password: ADMIN.password, display_name: ADMIN.name, locale: "en" } });
  if (![201, 409].includes(res.status())) throw new Error(`could not create the e2e admin: ${res.status()} ${await res.text()}`);
  await ctx.dispose();
}
