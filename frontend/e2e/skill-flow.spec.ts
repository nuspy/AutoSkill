import { expect, test } from "@playwright/test";
import { createProject, registerUser } from "./helpers";

test("interview -> confirmation -> draft -> trial with an online install address -> download link", async ({ page }) => {
  await registerUser(page, "Bea");
  const projectId = await createProject(page, "Invoices");

  // describe the task; the demo provider fills the knowledge document in one turn
  await page.goto(`/p/${projectId}/skills/new`);
  await page.getByLabel("Give this skill a short name").fill("Invoice check");
  await page.getByLabel("How do you do this task today?").fill("Every Monday I check supplier invoices against purchase orders and email accounting.");
  await page.getByRole("button", { name: "Start the interview" }).click();
  // the supervisor proceeds straight to the summary; the person confirms it
  await page.getByRole("button", { name: "Yes, that is right" }).click({ timeout: 60_000 });
  // the interview completes and drafting starts right away
  await expect(page.getByText(/Understanding complete|Drafting/).first()).toBeVisible({ timeout: 60_000 });

  // the draft is generated automatically after the interview
  await page.goto(`/p/${projectId}`);
  await page.getByRole("link", { name: /Invoice check/ }).first().click();
  await page.getByRole("link", { name: "Versions" }).click();
  await expect(page.getByText("v0.1.0").first()).toBeVisible({ timeout: 60_000 });

  // trial on the agent: the launcher shows the online installation address
  await page.getByRole("button", { name: "Try on my agent" }).first().click();
  await page.getByRole("button", { name: "Create trial" }).click();
  await expect(page.getByText("Installation file (online address)")).toBeVisible();
  const address = await page.locator("pre").filter({ hasText: /\/dl\/.*\/INSTALL\.md/ }).first().innerText();
  expect(address).toMatch(/\/dl\/[A-Za-z0-9_-]+\/INSTALL\.md$/);
  await page.getByRole("button", { name: "Open trial" }).click();
  await expect(page.getByText("Waiting for the installation")).toBeVisible();

  // the address really serves the description without a login
  const res = await page.request.get(address.replace(/^http:\/\/127\.0\.0\.1:\d+/, ""));
  expect(res.status()).toBe(200);
  expect(await res.text()).toContain("Download links");

  // a permanent download link can be created from the install tab of the version
  await page.goto(`/p/${projectId}`);
  await page.getByRole("link", { name: /Invoice check/ }).first().click();
  await page.getByRole("link", { name: "Versions" }).click();
  await page.getByRole("button", { name: "Install" }).first().click();
  await page.getByRole("button", { name: "Create link" }).click();
  await expect(page.getByText("Link created")).toBeVisible();
  await expect(page.locator("span.font-mono").filter({ hasText: /\/dl\// }).first()).toBeVisible();
});
