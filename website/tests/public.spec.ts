import { expect, test } from "@playwright/test";

const PAGES = ["", "/how-it-works", "/features", "/privacy", "/download", "/faq", "/signin", "/signup"];

test("a path without a language goes to the visitor's language", async ({ browser }) => {
  // the browser's language setting becomes its Accept-Language header
  for (const [locale, lang] of [["ar-JO", "ar"], ["en-GB", "en"], ["fr-FR", "en"]]) {
    const context = await browser.newContext({ locale });
    const page = await context.newPage();
    await page.goto("/features");
    await expect(page).toHaveURL(new RegExp(`/${lang}/features$`));
    await context.close();
  }
});

for (const lang of ["en", "ar"]) {
  test(`every public page works in ${lang}`, async ({ page }) => {
    for (const path of PAGES) {
      const response = await page.goto(`/${lang}${path}`);
      expect(response?.status(), path).toBe(200);
      await expect(page.locator("html")).toHaveAttribute("lang", lang);
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
      await expect(page.locator("h1")).toHaveCount(1);
      expect(await page.title()).toContain("Office Assistant");
    }
  });
}

test("the language switch keeps the page", async ({ page }) => {
  await page.goto("/en/privacy");
  await page.getByRole("link", { name: "Switch to Arabic" }).click();
  await expect(page).toHaveURL(/\/ar\/privacy$/);
  await expect(page.locator("h1")).toHaveText("الخصوصية");
  await page.getByRole("link", { name: "التبديل إلى الإنجليزية" }).click();
  await expect(page).toHaveURL(/\/en\/privacy$/);
});

test("the theme switch is remembered", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/en");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: "Switch to light theme" })).toBeVisible();
});

test("the download page shows the latest GitHub release", async ({ page }) => {
  await page.goto("/en/download");
  const version = page.getByTestId("version");
  if (await version.count()) {
    await expect(version).toHaveText(/^v\d+\.\d+\.\d+/);
    await expect(page.getByTestId("total-size")).toHaveText(/GB|MB/);
    const installer = page.getByRole("link", { name: "Download the installer" });
    await expect(installer).toHaveAttribute("href", /github\.com\/.+\/releases\/download\/.+\.exe$/);
    await expect(page.getByRole("link", { name: "View on GitHub" })).toHaveAttribute("href", /github\.com\/marwan55hatem\/AI-Office-Assistant-App\/releases/);
    await expect(page.getByTestId("assets").locator("li")).not.toHaveCount(0);
  } else {
    await expect(page.getByText("The release list could not be loaded right now.")).toBeVisible();   // GitHub unreachable
  }
  await expect(page.getByText("Windows 10 or 11, 64-bit")).toBeVisible();
  await expect(page.getByText(/NVIDIA GPU is recommended/)).toBeVisible();
});

test("the signed-in area needs a session", async ({ page }) => {
  await page.goto("/en/app/dashboard");
  await expect(page).toHaveURL(/\/en\/signin\?next=%2Fen%2Fapp%2Fdashboard$/);
});

test("an unknown language is a 404", async ({ page }) => {
  const response = await page.goto("/de/features", { waitUntil: "commit" });
  // /de is not a language: it is treated as a path and sent to /en/de/features, which does not exist
  await expect(page).toHaveURL(/\/en\/de\/features$/);
  expect([404, 200]).toContain(response?.status() ?? 404);
  await expect(page.locator("body")).toContainText(/404|could not be found/i);
});
