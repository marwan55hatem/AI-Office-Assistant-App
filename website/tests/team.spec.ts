import { expect, test } from "@playwright/test";

import { API, apiCompany, apiEmployee, apiSessions, signIn } from "./helpers";

test("the manager's reports show the team's numbers", async ({ page, request }) => {
  const company = await apiCompany(request);
  const anna = await apiEmployee(request, company, "Anna Hamdan");
  const ben = await apiEmployee(request, company, "Ben Okafor");
  await apiSessions(request, anna.headers, 0.85);
  await apiSessions(request, ben.headers, 0.6);
  await signIn(page, company.email);
  const kpis = page.getByTestId("kpis");
  await expect(kpis).toContainText("Focus");
  await expect(kpis.locator(".value").first()).not.toHaveText("0%");
  await expect(kpis).toContainText("2 employees");
  const ranking = page.getByTestId("ranking");
  await expect(ranking.locator("tbody tr")).toHaveCount(2);
  await expect(ranking.locator("tbody tr").first()).toContainText("Anna Hamdan");   // best focus first
  await page.getByLabel("Sort by").selectOption("name");
  await expect(ranking.locator("tbody tr").first()).toContainText("Anna Hamdan");
  await expect(page.getByTestId("page-label")).toHaveText("1–2 of 2");
  await expect(page.getByRole("img", { name: /Word/ })).toBeVisible();              // the apps donut
  // drill down into one employee
  await ranking.getByRole("button", { name: "Ben Okafor" }).click();
  await expect(page.getByLabel("Employee", { exact: true })).toHaveValue(ben.id);
  await expect(page.getByTestId("kpis")).toContainText("Days present");
  await expect(page.getByText("Team average")).toBeVisible();
  // the CSV export
  await page.getByLabel("Employee", { exact: true }).selectOption("");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await (await download).path();
  const { readFileSync } = await import("node:fs");
  const csv = readFileSync(file!, "utf-8");
  expect(csv).toContain("Anna Hamdan");
  expect(csv).toContain("Ben Okafor");
});

test("meeting request: asked on the web, accepted on the web", async ({ browser, request }) => {
  const company = await apiCompany(request);
  const anna = await apiEmployee(request, company, "Anna Hamdan");
  const employee = await (await browser.newContext()).newPage();
  await signIn(employee, anna.email);
  await employee.getByLabel("Topic").fill("Moving to the platform team");
  await employee.getByLabel("Short note (optional)").fill("Ten minutes is enough");
  await employee.getByRole("button", { name: "+ Add another time" }).click();
  await employee.getByRole("button", { name: "Send request" }).click();
  await expect(employee.getByText("Request sent. Your manager has been notified.")).toBeVisible();
  const card = employee.getByTestId("meeting");
  await expect(card).toContainText("Moving to the platform team");
  await expect(card).toContainText("Waiting for the manager");

  const boss = await (await browser.newContext()).newPage();
  await signIn(boss, company.email);
  await expect(boss.getByRole("link", { name: /Meetings/ }).locator(".badge")).toHaveText("1");
  await boss.getByRole("link", { name: /Meetings/ }).click();
  const request1 = boss.getByTestId("meeting");
  await expect(request1).toContainText("From Anna Hamdan");
  await request1.getByRole("radio").nth(1).check();
  await request1.getByRole("button", { name: "Accept selected time" }).click();
  await expect(boss.getByText("Done. The other side has been told.")).toBeVisible();

  await employee.getByLabel("Show").selectOption("accepted");
  await expect(employee.getByTestId("meeting")).toContainText("Booked");
  const events = await (await request.get(`${API}/calendar`, { headers: anna.headers })).json();
  expect(events.map((e: { title: string }) => e.title)).toContain("Meeting: Moving to the platform team");
});

test("the manager declines with a reason, and proposes other times", async ({ browser, request }) => {
  const company = await apiCompany(request);
  const anna = await apiEmployee(request, company, "Anna Hamdan");
  const soon = new Date(Date.now() + 2 * 864e5).toISOString();
  for (const topic of ["Budget", "Holiday plan"]) {
    await request.post(`${API}/meeting-requests`, { headers: anna.headers, data: { topic, proposed_times: [soon] } });
  }
  const boss = await (await browser.newContext()).newPage();
  await signIn(boss, company.email);
  await boss.goto("/en/app/meetings");
  const budget = boss.getByTestId("meeting").filter({ hasText: "Budget" });
  await budget.getByRole("button", { name: "Decline" }).click();
  await budget.getByLabel("Tell the employee why (required)").fill("Let's talk in January");
  await budget.getByRole("button", { name: "Decline" }).last().click();
  await expect(boss.getByText("Done. The other side has been told.")).toBeVisible();
  const holiday = boss.getByTestId("meeting").filter({ hasText: "Holiday plan" });
  await holiday.getByRole("button", { name: "Propose other times" }).click();
  await holiday.getByLabel("Optional note").fill("I'm away that week");
  await holiday.getByRole("button", { name: "Send times" }).click();
  await expect(holiday).toContainText("New times proposed");

  const employee = await (await browser.newContext()).newPage();
  await signIn(employee, anna.email);
  const mine = employee.getByTestId("meeting").filter({ hasText: "Holiday plan" });
  await expect(mine).toContainText("I'm away that week");
  await mine.getByRole("button", { name: "Accept selected time" }).click();
  await employee.getByLabel("Show").selectOption("all");             // straight away: the older answer must not win
  await expect(employee.getByTestId("meeting").filter({ hasText: "Holiday plan" })).toContainText("Booked");
  await expect(employee.getByTestId("meeting").filter({ hasText: "Budget" })).toContainText("Let's talk in January");
});

test("chat: live delivery and read receipts between two browsers", async ({ browser, request }) => {
  const company = await apiCompany(request);
  const anna = await apiEmployee(request, company, "Anna Hamdan");
  await apiEmployee(request, company, "Ben Okafor");
  const boss = await (await browser.newContext()).newPage();
  const employee = await (await browser.newContext()).newPage();
  await signIn(boss, company.email);
  await signIn(employee, anna.email);
  await boss.goto("/en/app/messages");
  await employee.goto("/en/app/messages");
  await expect(boss.getByText("● Live")).toBeVisible();
  await expect(employee.getByText("● Live")).toBeVisible();
  await boss.getByRole("button", { name: /Anna Hamdan/ }).click();

  await employee.getByRole("textbox").fill("Hi Sara, could I leave at 4 today?");
  await employee.keyboard.press("Enter");
  await expect(boss.getByTestId("messages")).toContainText("could I leave at 4 today?");   // live, no reload
  await expect(employee.getByTestId("mine").last()).toContainText("Read");                  // the manager has it open

  await boss.getByRole("textbox").fill("Sure, see you tomorrow!");
  await boss.getByRole("button", { name: "Send" }).click();
  await expect(employee.getByTestId("theirs").last()).toContainText("Sure, see you tomorrow!");
  await expect(employee.getByTestId("theirs").last()).toContainText("Sara Carter");
  await expect(boss.getByTestId("mine").last()).toContainText("Read");

  // Ben's conversation is separate and private
  await boss.getByRole("button", { name: /Ben Okafor/ }).click();
  await expect(boss.getByText("No messages yet. Say hello!")).toBeVisible();
  const other = await request.get(`${API}/chat/${anna.id}/messages`, { headers: (await apiEmployee(request, company, "Cleo Martin")).headers });
  expect(other.status()).toBe(404);
});

test("the manager disables an employee", async ({ page, request }) => {
  const company = await apiCompany(request);
  const anna = await apiEmployee(request, company, "Anna Hamdan");
  await signIn(page, company.email);
  await page.goto("/en/app/employees");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("row", { name: /Anna Hamdan/ }).getByRole("button", { name: "Disable" }).click();
  await expect(page.getByRole("row", { name: /Anna Hamdan/ })).toContainText("Disabled");
  const login = await request.post(`${API}/auth/login`, { data: { email: anna.email, password: "correct horse battery" } });
  expect(login.status()).toBe(403);                                     // "This account is disabled"
});
