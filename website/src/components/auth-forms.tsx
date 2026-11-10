"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";

import { authCall, type Me } from "@/lib/client";
import type { Dict, Locale } from "@/lib/i18n";

function message(t: Dict, error: string) {
  if (error === "offline") return t.auth.errorOffline;
  if (error === "error") return t.auth.errorGeneric;
  return error;
}

function safeNext(lang: Locale, next: string | null) {
  // only a path inside this site's signed-in area (no "//evil.example" redirects)
  return next && next.startsWith(`/${lang}/app`) && !next.startsWith("//") ? next : `/${lang}/app`;
}

export function SignInForm({ lang, t }: { lang: Locale; t: Dict }) {
  const router = useRouter();
  const search = useSearchParams();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ids = { email: useId(), password: useId(), error: useId() };

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    const result = await authCall<Me>("login", {
      email: form.get("email"), password: form.get("password"), remember: form.get("remember") === "on",
    });
    setBusy(false);
    if (!result.ok) {
      setError(message(t, result.error));
      return;
    }
    router.push(safeNext(lang, search.get("next")));
    router.refresh();
  }

  return (
    <form onSubmit={submit} noValidate={false} aria-describedby={error ? ids.error : undefined}>
      <div className="field">
        <label htmlFor={ids.email}>{t.auth.email}</label>
        <input id={ids.email} name="email" type="email" autoComplete="email" required />
      </div>
      <div className="field">
        <label htmlFor={ids.password}>{t.auth.password}</label>
        <input id={ids.password} name="password" type="password" autoComplete="current-password" required />
      </div>
      <div className="field">
        <label className="check"><input type="checkbox" name="remember" defaultChecked /> {t.auth.remember}</label>
      </div>
      {error ? <p id={ids.error} className="error" role="alert">{error}</p> : null}
      <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: "100%" }}>
        {busy ? t.auth.working : t.auth.submitSignIn}
      </button>
      <p className="muted" style={{ marginTop: 16 }}>
        {t.auth.noAccount} <Link href={`/${lang}/signup`}>{t.nav.signUp}</Link>
      </p>
    </form>
  );
}

export function SignUpForm({ lang, t }: { lang: Locale; t: Dict }) {
  const router = useRouter();
  const search = useSearchParams();
  const invite = search.get("invite");
  const [tab, setTab] = useState<"company" | "join">(invite || search.get("tab") === "join" ? "join" : "company");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);
  const id = useId();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    if (tab === "company") {
      const result = await authCall<Me>("register", {
        company_name: form.get("company_name"), owner_name: form.get("full_name"),
        email: form.get("email"), password: form.get("password"),
      });
      setBusy(false);
      if (!result.ok) return setError(message(t, result.error));
      router.push(`/${lang}/app`);
      router.refresh();
      return;
    }
    const result = await authCall("join", {
      full_name: form.get("full_name"), email: form.get("email"), password: form.get("password"),
      ...(invite ? { invite_token: invite } : { company_code: String(form.get("company_code") ?? "").trim() }),
    });
    setBusy(false);
    if (!result.ok) return setError(message(t, result.error));
    setDone(t.auth.joined);
  }

  if (done) {
    return (
      <div>
        <p className="success" role="status">{done}</p>
        <Link className="btn btn-primary" href={`/${lang}/signin`}>{t.nav.signIn}</Link>
      </div>
    );
  }

  return (
    <div>
      <div className="tabs" role="tablist" aria-label={t.auth.signUpTitle}>
        <button type="button" role="tab" aria-selected={tab === "company"} aria-controls={`${id}-panel`}
                id={`${id}-company`} onClick={() => setTab("company")}>{t.auth.tabCompany}</button>
        <button type="button" role="tab" aria-selected={tab === "join"} aria-controls={`${id}-panel`}
                id={`${id}-join`} onClick={() => setTab("join")}>{t.auth.tabJoin}</button>
      </div>
      <form id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`} onSubmit={submit}>
        {tab === "company" ? (
          <div className="field">
            <label htmlFor={`${id}-company-name`}>{t.auth.companyName}</label>
            <input id={`${id}-company-name`} name="company_name" type="text" autoComplete="organization" required maxLength={120} />
          </div>
        ) : null}
        <div className="field">
          <label htmlFor={`${id}-name`}>{t.auth.fullName}</label>
          <input id={`${id}-name`} name="full_name" type="text" autoComplete="name" required maxLength={120} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-email`}>{t.auth.email}</label>
          <input id={`${id}-email`} name="email" type="email" autoComplete="email" required />
        </div>
        <div className="field">
          <label htmlFor={`${id}-password`}>{t.auth.password}</label>
          <input id={`${id}-password`} name="password" type="password" autoComplete="new-password" required minLength={8}
                 maxLength={128} aria-describedby={`${id}-password-hint`} />
          <p id={`${id}-password-hint`} className="hint">{t.auth.passwordHint}</p>
        </div>
        {tab === "join" && !invite ? (
          <div className="field">
            <label htmlFor={`${id}-code`}>{t.auth.companyCode}</label>
            <input id={`${id}-code`} name="company_code" type="text" required minLength={4} maxLength={16}
                   pattern="[A-Za-z0-9]+" autoCapitalize="characters" aria-describedby={`${id}-code-hint`} />
            <p id={`${id}-code-hint`} className="hint">{t.auth.companyCodeHint}</p>
          </div>
        ) : null}
        {error ? <p className="error" role="alert">{error}</p> : null}
        <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: "100%" }}>
          {busy ? t.auth.working : tab === "company" ? t.auth.submitCompany : t.auth.submitJoin}
        </button>
        <p className="muted" style={{ marginTop: 16 }}>
          {t.auth.haveAccount} <Link href={`/${lang}/signin`}>{t.nav.signIn}</Link>
        </p>
      </form>
    </div>
  );
}
