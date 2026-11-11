import { expect, test } from "@playwright/test";

import { API, apiCompany, PASSWORD, signIn, unique } from "./helpers";

test("sign up a company, then go on to the download", async ({ page }) => {
  const email = unique("owner");
  await page.goto("/en/signup");
  await page.getByLabel("Company name").fill("Northwind Studio");
  await page.getByLabel("Your full name").fill("Sara Carter");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create company" }).click();
  await expect(page).toHaveURL(/\/en\/app$/);                                  // the portal overview
  await expect(page.getByRole("heading", { level: 1, name: "Welcome, Sara Carter" })).toBeVisible();
  await expect(page.getByText("Northwind Studio · Manager")).toBeVisible();
  await expect(page.getByTestId("download-card")).toBeVisible();
  await expect(page.getByTestId("overview-members")).toContainText("0");

  // the session is in httpOnly cookies: page scripts cannot read it
  expect(await page.evaluate(() => document.cookie)).not.toContain("oa_rt");
  const cookies = await page.context().cookies();
  expect(cookies.find((c) => c.name === "oa_rt")?.httpOnly).toBe(true);
  expect(cookies.find((c) => c.name === "oa_rt")?.sameSite).toBe("Lax");

  await page.getByRole("link", { name: "Download", exact: true }).first().click();
  await expect(page).toHaveURL(/\/en\/download$/);
  await expect(page.getByRole("heading", { level: 1, name: "Download" })).toBeVisible();
});

test("sign out and sign in again; a wrong password is refused", async ({ page, request }) => {
  const company = await apiCompany(request);
  await signIn(page, company.email);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/en$/);
  expect((await page.context().cookies()).find((c) => c.name === "oa_rt")).toBeUndefined();

  await page.goto("/en/signin");
  await page.getByLabel("E-mail").fill(company.email);
  await page.getByLabel("Password", { exact: true }).fill("not the password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/en\/signin/);
  await signIn(page, company.email);
  await expect(page).toHaveURL(/\/en\/app$/);
});

test("sign in in Arabic", async ({ page, request }) => {
  const company = await apiCompany(request);
  await signIn(page, company.email, "ar");
  await expect(page.getByRole("heading", { level: 1, name: "أهلاً، Sara Carter" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
});

test("an employee joins with the code, the manager approves on the web", async ({ browser, request }) => {
  const company = await apiCompany(request);
  const employeeEmail = unique("anna");
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto("/en/signup");
  await visitor.getByRole("tab", { name: "Join a company" }).click();
  await visitor.getByLabel("Your full name").fill("Anna Hamdan");
  await visitor.getByLabel("E-mail").fill(employeeEmail);
  await visitor.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await visitor.getByLabel("Company code").fill(company.code);
  await visitor.getByRole("button", { name: "Request to join" }).click();
  await expect(visitor.getByRole("status")).toContainText("Your request was sent");

  const boss = await (await browser.newContext()).newPage();
  await signIn(boss, company.email);
  await boss.getByRole("link", { name: "Employees" }).click();
  const pending = boss.getByTestId("pending");
  await expect(pending).toContainText("Anna Hamdan");
  await pending.getByRole("button", { name: "Approve" }).click();
  await expect(boss.getByTestId("team")).toContainText("Anna Hamdan");
  await expect(boss.getByText("Nobody is waiting.")).toBeVisible();

  await signIn(visitor, employeeEmail);
  await expect(visitor).toHaveURL(/\/en\/app$/);                         // employees land on the overview too
  await expect(visitor.getByTestId("overview-members")).toHaveCount(0);  // ...without the manager's cards
  await expect(visitor.getByRole("link", { name: "Employees" })).toHaveCount(0);
  await visitor.goto("/en/app/dashboard");                                 // managers only
  await expect(visitor).toHaveURL(/\/en\/app\/meetings$/);
});

test("an invite link made on the web lets someone join", async ({ browser, request }) => {
  const company = await apiCompany(request);
  const boss = await (await browser.newContext()).newPage();
  await signIn(boss, company.email);
  await boss.goto("/en/app/employees");
  const invitedEmail = unique("omar");          // an invite for an address only accepts that address
  await boss.getByLabel("E-mail (optional)").fill(invitedEmail);
  await boss.getByRole("button", { name: "Create invite link" }).click();
  const link = await boss.getByRole("textbox", { name: "Invite link (shown once):" }).inputValue();
  expect(link).toMatch(/\/en\/signup\?invite=/);

  const guest = await (await browser.newContext()).newPage();
  await guest.goto(link);
  await expect(guest.getByRole("tab", { name: "Join a company" })).toHaveAttribute("aria-selected", "true");
  await expect(guest.getByLabel("Company code")).toHaveCount(0);           // the invite replaces the code
  await guest.getByLabel("Your full name").fill("Omar Invited");
  await guest.getByLabel("E-mail").fill(invitedEmail);
  await guest.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await guest.getByRole("button", { name: "Request to join" }).click();
  await expect(guest.getByRole("status")).toBeVisible();
  await boss.reload();
  await expect(boss.getByTestId("pending")).toContainText("Omar Invited");
});

test("cross-site requests are refused", async ({ request }) => {
  const forged = await request.post("/api/auth/login", {
    headers: { origin: "https://evil.example", "content-type": "application/json" },
    data: { email: "x@y.com", password: "whatever" },
  });
  expect(forged.status()).toBe(403);
  const noHeader = await request.post("/api/proxy/invites", { data: {} });
  expect(noHeader.status()).toBe(403);
  // only the parts of the API the website needs are reachable through it
  const blocked = await request.get("/api/proxy/sessions/history", { headers: { "x-oa-request": "1" } });
  expect(blocked.status()).toBe(404);
  const traversal = await request.get("/api/proxy/users/..%2F..%2Fhealth", { headers: { "x-oa-request": "1" } });
  expect([401, 404]).toContain(traversal.status());
  // sanity: the API itself is up
  expect((await request.get(`${API}/health`)).ok()).toBeTruthy();
});
