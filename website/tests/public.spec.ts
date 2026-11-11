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
      expect(await page.title()).toContain(lang === "en" ? "Office Assistant" : "المساعد المكتبي الذكي");
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

test("unknown pages get the styled 404 in the right language", async ({ page }) => {
  // /de is not a language: it is treated as a path and sent to /en/de/features, which does not exist
  let response = await page.goto("/de/features");
  await expect(page).toHaveURL(/\/en\/de\/features$/);
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  response = await page.goto("/ar/no-such-page");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "الصفحة غير موجودة" })).toBeVisible();
  await page.getByRole("link", { name: "العودة إلى الصفحة الرئيسية" }).click();
  await expect(page).toHaveURL(/\/ar$/);
});

test("the language choice is remembered for addresses without a language", async ({ page }) => {
  await page.goto("/en");
  await page.getByRole("link", { name: "Switch to Arabic" }).click();
  await expect(page).toHaveURL(/\/ar$/);
  await page.goto("/features");
  await expect(page).toHaveURL(/\/ar\/features$/);
});

test("every page sends a strict content security policy with a fresh nonce", async ({ request }) => {
  const first = await request.get("/en");
  const second = await request.get("/en");
  const csp = first.headers()["content-security-policy"];
  expect(csp).toContain("script-src 'self' 'nonce-");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("object-src 'none'");
  expect(csp).not.toEqual(second.headers()["content-security-policy"]);       // a new nonce every time
  expect(first.headers()["x-content-type-options"]).toBe("nosniff");
  expect(first.headers()["referrer-policy"]).toBe("strict-origin-when-cross-origin");
});

test("pages show no console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${page.url()}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${page.url()}: ${e.message}`));
  for (const path of ["/en", "/ar", "/en/download", "/en/signup", "/en/forgot-password", "/en/faq"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  expect(errors).toEqual([]);
});

test("GitHub links open in a new tab without an opener", async ({ page }) => {
  await page.goto("/en");
  const github = page.getByRole("link", { name: /View on GitHub/ });
  await expect(github).toHaveAttribute("target", "_blank");
  await expect(github).toHaveAttribute("rel", "noopener noreferrer");
  await expect(github).toHaveAttribute("href", "https://github.com/marwan55hatem/AI-Office-Assistant-App");
});

test("on a phone the menu opens and closes, with no sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  for (const lang of ["en", "ar"]) {
    await page.goto(`/${lang}`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  }
  await page.goto("/en");
  const nav = page.getByRole("navigation", { name: "Menu" });
  await expect(nav).toBeHidden();
  await page.getByRole("button", { name: "Open the menu" }).click();
  await expect(nav).toBeVisible();
  await expect(page.getByRole("button", { name: "Close the menu" })).toHaveAttribute("aria-expanded", "true");
  await nav.getByRole("link", { name: "Privacy" }).click();
  await expect(page).toHaveURL(/\/en\/privacy$/);
  await expect(nav).toBeHidden();
});
