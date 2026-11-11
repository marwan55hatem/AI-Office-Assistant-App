import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ForgotForm, ResetForm, SignInForm, SignUpForm } from "@/components/auth-forms";
import { DownloadCard } from "@/components/download-card";
import { api, authCall } from "@/lib/client";
import { en as t } from "@/lib/i18n/en";
import { ar } from "@/lib/i18n/ar";
import { router, search } from "./setup";

type Call = { url: string; init: RequestInit };
let calls: Call[] = [];

function mockFetch(status = 200, body: unknown = {}) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }));
}

beforeEach(() => mockFetch());
afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("sends the site's own header and JSON", async () => {
    mockFetch(200, { ok: 1 });
    const result = await api("users", "POST", { a: 1 });
    expect(result).toEqual({ ok: true, status: 200, data: { ok: 1 } });
    expect(calls[0].url).toBe("/api/proxy/users");
    expect(calls[0].init.headers).toMatchObject({ "x-oa-request": "1", "content-type": "application/json" });
    expect(calls[0].init.body).toBe('{"a":1}');
  });
  it("turns server errors into readable messages", async () => {
    mockFetch(422, { detail: [{ msg: "Value error, proposed times must be in the future" }] });
    expect(await api("x")).toMatchObject({ ok: false, error: "proposed times must be in the future" });
    mockFetch(409, { detail: "This request is declined" });
    expect(await api("x")).toMatchObject({ ok: false, status: 409, error: "This request is declined" });
    mockFetch(503, { detail: "offline" });
    expect(await authCall("login", {})).toMatchObject({ ok: false, error: "offline" });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    expect(await api("x")).toEqual({ ok: false, status: 0, error: "offline" });
  });
  it("uses GET for the session and POST for the rest", async () => {
    await authCall("session");
    await authCall("forgot", { email: "a@b.co" });
    expect(calls.map((c) => [c.url, c.init.method])).toEqual([["/api/auth/session", "GET"], ["/api/auth/forgot", "POST"]]);
  });
});

describe("sign-in form", () => {
  it("checks the fields before calling the server", async () => {
    render(<SignInForm lang="en" t={t} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Please fill in this field.")).toBeTruthy();
    expect(screen.getByLabelText("E-mail").getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText("E-mail"));
    expect(calls).toHaveLength(0);
  });
  it("signs in and goes to the requested page inside the portal only", async () => {
    mockFetch(200, { user: { full_name: "Sara" } });
    search.params = new URLSearchParams({ next: "/en/app/meetings" });
    render(<SignInForm lang="en" t={t} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "sara@northwind.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/en/app/meetings"));
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ email: "sara@northwind.com", password: "correct horse battery", remember: true });
  });
  it("never redirects outside the portal", async () => {
    mockFetch(200, {});
    search.params = new URLSearchParams({ next: "//evil.example/steal" });
    render(<SignInForm lang="en" t={t} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "sara@northwind.com");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/en/app"));
  });
  it("shows the server's answer", async () => {
    mockFetch(401, { detail: "Wrong e-mail or password" });
    render(<SignInForm lang="en" t={t} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "sara@northwind.com");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Wrong e-mail or password")).toBeTruthy();
  });
});

describe("sign-up form", () => {
  it("needs a 10-character password and sends the company", async () => {
    mockFetch(201, {});
    render(<SignUpForm lang="en" t={t} />);
    await userEvent.type(screen.getByLabelText("Company name"), "Northwind");
    await userEvent.type(screen.getByLabelText("Your full name"), "Sara Carter");
    await userEvent.type(screen.getByLabelText("E-mail"), "sara@northwind.com");
    await userEvent.type(screen.getByLabelText("Password"), "ninechars");
    await userEvent.click(screen.getByRole("button", { name: "Create company" }));
    expect(screen.getByText("Use at least 10 characters.")).toBeTruthy();
    expect(calls).toHaveLength(0);
    await userEvent.type(screen.getByLabelText("Password"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Create company" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toBe("/api/auth/register");
    expect(JSON.parse(String(calls[0].init.body))).toMatchObject({ company_name: "Northwind", owner_name: "Sara Carter" });
  });
  it("an invite link opens the join tab without a company code", async () => {
    search.params = new URLSearchParams({ invite: "t".repeat(40) });
    render(<SignUpForm lang="en" t={t} />);
    expect(screen.getByRole("tab", { name: "Join a company" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByLabelText("Company code")).toBeNull();
  });
  it("speaks Arabic", () => {
    render(<SignUpForm lang="ar" t={ar} />);
    expect(screen.getByRole("tab", { name: "إنشاء شركة" })).toBeTruthy();
    expect(screen.getByText("10 أحرف على الأقل.")).toBeTruthy();
  });
});

describe("password reset forms", () => {
  it("forgot: the same answer for every address", async () => {
    mockFetch(202, { detail: "sent" });
    render(<ForgotForm lang="en" t={t} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "anyone@northwind.com");
    await userEvent.click(screen.getByRole("button", { name: "Send the link" }));
    expect((await screen.findByRole("status")).textContent).toContain("If an account uses this address");
  });
  it("reset: no token, no form", () => {
    render(<ResetForm lang="en" t={t} />);
    expect(screen.getByRole("alert").textContent).toContain("This link is incomplete");
  });
  it("reset: both passwords must match before anything is sent", async () => {
    mockFetch(204);
    search.params = new URLSearchParams({ token: "k".repeat(43) });
    render(<ResetForm lang="en" t={t} />);
    await userEvent.type(screen.getByLabelText("New password"), "a brand new secret");
    await userEvent.type(screen.getByLabelText("New password again"), "something else!!");
    await userEvent.click(screen.getByRole("button", { name: "Save the new password" }));
    expect(screen.getByText("The two passwords are not the same.")).toBeTruthy();
    expect(calls).toHaveLength(0);
    await userEvent.clear(screen.getByLabelText("New password again"));
    await userEvent.type(screen.getByLabelText("New password again"), "a brand new secret");
    await userEvent.click(screen.getByRole("button", { name: "Save the new password" }));
    expect((await screen.findByRole("status")).textContent).toContain("Your password has been changed");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ token: "k".repeat(43), new_password: "a brand new secret" });
  });
});

describe("download card", () => {
  const release = {
    version: "v1.0.0", published: "2026-10-19T18:29:07Z", url: "https://github.com/x/y/releases/tag/v1.0.0",
    installerUrl: "https://github.com/x/y/releases/download/v1.0.0/OfficeAssistant-Setup.exe",
    assets: [{ name: "OfficeAssistant-Setup.exe", size: 2_695_528, url: "https://example.test/setup.exe" }],
  };
  it("a release: the installer button, version and files", () => {
    render(<DownloadCard release={release} lang="en" t={t} />);
    const button = screen.getByRole("link", { name: "Download the installer" });
    expect(button.getAttribute("href")).toBe(release.installerUrl);
    expect(screen.getByText("v1.0.0")).toBeTruthy();
    expect(screen.getByText("OfficeAssistant-Setup.exe")).toBeTruthy();
    const github = screen.getByRole("link", { name: /View on GitHub/ });
    expect(github.getAttribute("rel")).toBe("noopener noreferrer");
    expect(github.getAttribute("target")).toBe("_blank");
  });
  it("no release yet: the button is disabled and says why", () => {
    render(<DownloadCard release={null} lang="en" t={t} />);
    const button = screen.getByRole("button", { name: "Download the installer" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-describedby")).toBe("no-release");
    expect(screen.getByText(/There is no release to download yet/)).toBeTruthy();
  });
  it("GitHub unreachable: a link to the releases page", () => {
    render(<DownloadCard release="unavailable" lang="en" t={t} />);
    expect(screen.getByRole("link", { name: /View on GitHub/ }).getAttribute("href")).toMatch(/\/releases$/);
  });
});
