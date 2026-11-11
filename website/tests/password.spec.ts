import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { apiCompany, PASSWORD, signIn } from "./helpers";

const COMPOSE = path.resolve(__dirname, "../../backend/docker-compose.yml");

/** The newest reset link the API queued (the test API runs without its mail sender, so the
 *  queued e-mail still holds it). Read straight from the database. */
function latestResetPath(): string {
  const out = execFileSync("docker", ["compose", "-f", COMPOSE, "exec", "-T", "db", "psql", "-U", "office_owner", "-d", "office",
    "-qtAc", "SELECT payload->>'path' FROM email_log WHERE template = 'password_reset' ORDER BY id DESC LIMIT 1"]);
  return out.toString().trim();
}

test("forgot password: e-mail link, new password, sign in with it", async ({ page, request }) => {
  const company = await apiCompany(request);
  await page.goto("/en/signin");
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page).toHaveURL(/\/en\/forgot-password$/);
  await page.getByLabel("E-mail").fill(company.email);
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByRole("status")).toContainText("If an account uses this address");

  const link = latestResetPath();
  expect(link).toMatch(/^\/en\/reset-password\?token=/);
  await page.goto(link);
  await page.getByLabel("New password", { exact: true }).fill("short");
  await page.getByLabel("New password again").fill("short");
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page.getByText("Use at least 10 characters.")).toBeVisible();
  await page.getByLabel("New password", { exact: true }).fill("a brand new secret");
  await page.getByLabel("New password again").fill("a different secret");
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page.getByText("The two passwords are not the same.")).toBeVisible();
  await page.getByLabel("New password again").fill("a brand new secret");
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page.getByRole("status")).toContainText("Your password has been changed");

  // the old password no longer works, the new one does; the link cannot be used twice
  await page.goto("/en/signin");
  await page.getByLabel("E-mail").fill(company.email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("Wrong e-mail or password")).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill("a brand new secret");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/en\/app$/);
  await page.goto(link);
  await page.getByLabel("New password", { exact: true }).fill("yet another secret");
  await page.getByLabel("New password again").fill("yet another secret");
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page.getByText(/invalid or has expired/)).toBeVisible();
});

test("an unknown address gets the same answer", async ({ page }) => {
  await page.goto("/en/forgot-password");
  await page.getByLabel("E-mail").fill("nobody-here@northwind-demo.com");
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByRole("status")).toContainText("If an account uses this address");
});

test("a reset page without a token says what to do", async ({ page }) => {
  await page.goto("/ar/reset-password");
  await expect(page.getByRole("alert").filter({ hasText: "هذا الرابط غير مكتمل" })).toBeVisible();
  await expect(page.getByRole("link", { name: "اطلب رابطاً جديداً" })).toBeVisible();
});

test("form errors are shown next to the field and announced", async ({ page }) => {
  await page.goto("/en/signup");
  await page.getByRole("button", { name: "Create company" }).click();
  const company = page.getByLabel("Company name");
  await expect(company).toHaveAttribute("aria-invalid", "true");
  await expect(company).toBeFocused();                                  // the first problem gets the focus
  await company.fill("Northwind");
  await page.getByLabel("Your full name").fill("Sara");
  await page.getByLabel("E-mail").fill("not-an-email");
  await page.getByLabel("Password", { exact: true }).fill("ninechars");
  await page.getByRole("button", { name: "Create company" }).click();
  await expect(page.getByText("Enter a valid e-mail address.")).toBeVisible();
  await expect(page.getByText("Use at least 10 characters.")).toBeVisible();
  await expect(page.getByLabel("E-mail")).toBeFocused();
});

test("the portal links lead to each part", async ({ page, request }) => {
  const company = await apiCompany(request);
  await signIn(page, company.email);
  await page.getByTestId("overview-reports").getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/en\/app\/dashboard$/);
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page).toHaveURL(/\/en\/app$/);
});
