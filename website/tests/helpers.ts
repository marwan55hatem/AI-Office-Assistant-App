import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = process.env.API_URL ?? "http://localhost:8766";
export const PASSWORD = "correct horse battery";

let counter = 0;
export function unique(prefix: string) {
  counter += 1;
  return `${prefix}${Date.now().toString(36)}${counter}${Math.random().toString(36).slice(2, 6)}@northwind-demo.com`;
}

/** Create a company straight through the API (fast set-up for tests that are not about sign-up). */
export async function apiCompany(request: APIRequestContext, name = "Northwind Studio") {
  const email = unique("boss");
  const tokens = await (await request.post(`${API}/auth/register-company`, {
    data: { company_name: name, owner_name: "Sara Carter", email, password: PASSWORD },
  })).json();
  const headers = { authorization: `Bearer ${tokens.access_token}` };
  const code = (await (await request.get(`${API}/company`, { headers })).json()).join_code as string;
  return { email, headers, code };
}

/** An approved employee of that company; returns their e-mail, API headers and id. */
export async function apiEmployee(request: APIRequestContext, company: { headers: Record<string, string>; code: string },
  fullName: string) {
  const email = unique(fullName.split(" ")[0].toLowerCase());
  await request.post(`${API}/auth/join`, { data: { full_name: fullName, email, password: PASSWORD, company_code: company.code } });
  const pending = await (await request.get(`${API}/users?status=pending`, { headers: company.headers })).json();
  const id = pending.find((u: { email: string }) => u.email === email).id as string;
  await request.post(`${API}/users/${id}/approve`, { headers: company.headers });
  const tokens = await (await request.post(`${API}/auth/login`, { data: { email, password: PASSWORD } })).json();
  return { email, id, headers: { authorization: `Bearer ${tokens.access_token}` } };
}

export async function signIn(page: Page, email: string, lang = "en") {
  await page.goto(`/${lang}/signin`);
  await page.getByLabel(lang === "en" ? "E-mail" : "البريد الإلكتروني").fill(email);
  await page.getByLabel(lang === "en" ? "Password" : "كلمة المرور", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: lang === "en" ? "Sign in" : "تسجيل الدخول", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/${lang}/app(/|$|\\?)`));
}

/** A few days of work sessions for an employee, so the reports have data. */
export async function apiSessions(request: APIRequestContext, headers: Record<string, string>, focusRatio: number) {
  const sessions = [];
  for (let back = 0; back < 5; back++) {
    const day = new Date(Date.now() - back * 864e5);
    const local = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    const tracked = 6 * 3600;
    const focus = Math.round(tracked * focusRatio);
    const away = 1200;
    sessions.push({
      id: crypto.randomUUID(), local_date: local, started_at: new Date().toISOString(), ended_at: new Date().toISOString(),
      focus_seconds: focus, distraction_seconds: tracked - focus - away, away_seconds: away,
      apps: [{ name: "Word", category: "productive", seconds: focus }, { name: "YouTube", category: "distraction", seconds: tracked - focus - away }],
    });
  }
  const response = await request.post(`${API}/sessions/sync`, { headers, data: { sessions } });
  expect(response.ok()).toBeTruthy();
}
