import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { apiCompany, apiEmployee, apiSessions, signIn } from "./helpers";

const PUBLIC = ["", "/how-it-works", "/features", "/privacy", "/download", "/faq", "/signin", "/signup"];

async function audit(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const summary = serious.map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  expect(summary, `${label}: WCAG 2.2 AA problems`).toEqual([]);
  return result.violations.length;
}

for (const theme of ["light", "dark"] as const) {
  for (const lang of ["en", "ar"]) {
    test(`public pages are accessible (${lang}, ${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme });
      for (const path of PUBLIC) {
        await page.goto(`/${lang}${path}`);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await audit(page, `/${lang}${path} ${theme}`);
      }
    });
  }
}

for (const theme of ["light", "dark"] as const) {
  test(`signed-in pages are accessible (${theme})`, async ({ page, request }) => {
    const company = await apiCompany(request);
    const anna = await apiEmployee(request, company, "Anna Hamdan");
    await apiSessions(request, anna.headers, 0.8);
    await page.emulateMedia({ colorScheme: theme });
    await signIn(page, company.email);
    for (const path of ["dashboard", "employees", "meetings", "messages"]) {
      await page.goto(`/en/app/${path}`);
      await expect(page.locator("h1")).toBeVisible();
      await page.waitForLoadState("networkidle");
      await audit(page, `/en/app/${path} ${theme}`);
    }
  });
}

test("the keyboard reaches the main content first", async ({ page }) => {
  await page.goto("/en");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await skip.press("Enter");
  await expect(page).toHaveURL(/#main$/);
});
