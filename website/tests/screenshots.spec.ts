import { expect, test } from "@playwright/test";

import { API, apiCompany, apiEmployee, apiSessions, signIn } from "./helpers";

/** Screenshots for the docs (runs only with SCREENSHOTS=1; files go to ../screenshots_redesign/cloud). */
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to make the screenshots");

const OUT = "../screenshots_redesign/cloud/phase8_";

test("public pages", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  for (const theme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto("/en");
    await page.screenshot({ path: `${OUT}home_${theme}.png`, fullPage: true });
  }
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/ar");
  await page.screenshot({ path: `${OUT}home_ar_rtl.png`, fullPage: true });
  await page.goto("/en/download");
  await page.screenshot({ path: `${OUT}download.png`, fullPage: true });
  await page.goto("/ar/privacy");
  await page.screenshot({ path: `${OUT}privacy_ar.png`, fullPage: true });
  await page.goto("/en/signup");
  await page.screenshot({ path: `${OUT}signup.png` });
});

test("signed-in pages", async ({ browser, request }) => {
  const company = await apiCompany(request);
  const people = [["Anna Hamdan", 0.86], ["Ben Okafor", 0.72], ["Cleo Martin", 0.6], ["Dan Petrov", 0.5]] as const;
  const staff = [];
  for (const [name, ratio] of people) {
    const person = await apiEmployee(request, company, name);
    await apiSessions(request, person.headers, ratio);
    staff.push(person);
  }
  const soon = (days: number, hour: number) => {
    const d = new Date(Date.now() + days * 864e5);
    d.setHours(hour, 0, 0, 0);
    return d.toISOString();
  };
  await request.post(`${API}/meeting-requests`, { headers: staff[0].headers,
    data: { topic: "Moving to the platform team", note: "Ten minutes is enough", proposed_times: [soon(1, 10), soon(2, 14)] } });
  await request.post(`${API}/meeting-requests`, { headers: staff[1].headers,
    data: { topic: "Training budget", proposed_times: [soon(3, 11)] } });
  await request.post(`${API}/chat/${staff[0].id}/messages`, { headers: staff[0].headers, data: { body: "Hi Sara, could I leave at 4 today? The plumber comes at 5." } });
  await request.post(`${API}/chat/${staff[0].id}/messages`, { headers: company.headers, data: { body: "Sure, no problem. See you tomorrow!" } });
  await request.post(`${API}/chat/${staff[2].id}/messages`, { headers: staff[2].headers, data: { body: "Sent you the invoices — the March one is late." } });

  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = await context.newPage();
  await signIn(page, company.email);
  for (const theme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto("/en/app/dashboard");
    await expect(page.getByTestId("ranking").locator("tbody tr")).toHaveCount(4);
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: `${OUT}dashboard_${theme}.png`, fullPage: true });
  }
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/en/app/meetings");
  await expect(page.getByTestId("meeting")).toHaveCount(2);
  await page.screenshot({ path: `${OUT}meetings_manager.png`, fullPage: true });
  await page.goto("/en/app/messages");
  await page.getByRole("button", { name: /Anna Hamdan/ }).click();
  await expect(page.getByText("● Live")).toBeVisible();
  await page.screenshot({ path: `${OUT}messages_manager.png` });
  await page.goto("/ar/app/employees");
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${OUT}employees_ar.png`, fullPage: true });
});
