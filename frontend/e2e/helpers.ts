import { expect, type Page } from "@playwright/test";

let counter = 0;

/** Register a fresh account through the UI (the very first one becomes the administrator). */
export async function registerUser(page: Page, name = "Alice") {
  counter += 1;
  const email = `${name.toLowerCase()}${Date.now()}${counter}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/$/);
  return email;
}

export async function createProject(page: Page, name = "Ops") {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).first().click();
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByText("Project created")).toBeVisible();
  await page.getByRole("link", { name: new RegExp(`^${name}`) }).first().click();
  await expect(page).toHaveURL(/\/p\//);
  return page.url().match(/\/p\/([^/]+)/)![1];
}

export async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
}
