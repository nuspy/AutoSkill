import { expect, test } from "@playwright/test";
import { createProject, registerUser } from "./helpers";

test("register, create a project, sign out and back in", async ({ page }) => {
  const email = await registerUser(page, "Alice");
  await createProject(page, "Ops");
  await expect(page.getByRole("heading", { name: "Ops" })).toBeVisible();
  await page.goto("/me");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
});

test("forgot-password page accepts any address", async ({ page }) => {
  await page.goto("/forgot");
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByText("a message with the reset link")).toBeVisible();
});
