"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";

import { authCall, type Me } from "@/lib/client";
import type { Dict, Locale } from "@/lib/i18n";
import { checkEmail, checkNewPassword, checkRequired, checkSame, firstProblem, type Problem } from "@/lib/validate";

type Errors = Record<string, string>;

function serverMessage(t: Dict, error: string) {
  if (error === "offline") return t.auth.errorOffline;
  if (error === "error") return t.auth.errorGeneric;
  return error;
}

function problemText(t: Dict, problem: Exclude<Problem, null>) {
  return t.auth[problem];
}

function safeNext(lang: Locale, next: string | null) {
  // only a path inside this site's signed-in area (no "//evil.example" redirects)
  return next && next.startsWith(`/${lang}/app`) && !next.startsWith("//") ? next : `/${lang}/app`;
}

/** A labelled input with its hint and (when wrong) an error that screen readers announce. */
function Field({ id, label, name, type = "text", error, hint, ...input }: {
  id: string; label: string; name: string; type?: string; error?: string; hint?: string;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const describedBy = [hint ? `${id}-hint` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} name={name} type={type} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />
      {hint ? <p id={`${id}-hint`} className="hint">{hint}</p> : null}
      {error ? <p id={`${id}-error`} className="error" role="alert">{error}</p> : null}
    </div>
  );
}

function focusField(form: HTMLFormElement, name: string) {
  (form.elements.namedItem(name) as HTMLElement | null)?.focus();
}

export function SignInForm({ lang, t }: { lang: Locale; t: Dict }) {
  const router = useRouter();
  const search = useSearchParams();
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const id = useId();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const email = String(data.get("email") ?? "");
    const password = String(data.get("password") ?? "");
    const problem = firstProblem({ email: checkEmail(email), password: checkRequired(password) });
    setErrors(problem ? { [problem[0]]: problemText(t, problem[1]) } : {});
    setError("");
    if (problem) return focusField(form, problem[0]);
    setBusy(true);
    const result = await authCall<Me>("login", { email, password, remember: data.get("remember") === "on" });
    setBusy(false);
    if (!result.ok) return setError(serverMessage(t, result.error));
    router.push(safeNext(lang, search.get("next")));
    router.refresh();
  }

  return (
    <form onSubmit={submit} noValidate>
      <Field id={`${id}-email`} label={t.auth.email} name="email" type="email" autoComplete="email" required error={errors.email} />
      <Field id={`${id}-password`} label={t.auth.password} name="password" type="password" autoComplete="current-password"
             required error={errors.password} />
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <label className="check"><input type="checkbox" name="remember" defaultChecked /> {t.auth.remember}</label>
        <Link className="link" href={`/${lang}/forgot-password`}>{t.auth.forgotLink}</Link>
      </div>
      {error ? <p className="error" role="alert">{error}</p> : null}
      <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: "100%" }}>
        {busy ? t.auth.working : t.auth.submitSignIn}
      </button>
      <p className="muted" style={{ marginTop: 16 }}>
        {t.auth.noAccount} <Link className="link" href={`/${lang}/signup`}>{t.nav.signUp}</Link>
      </p>
    </form>
  );
}

export function SignUpForm({ lang, t }: { lang: Locale; t: Dict }) {
  const router = useRouter();
  const search = useSearchParams();
  const invite = search.get("invite");
  const [tab, setTab] = useState<"company" | "join">(invite || search.get("tab") === "join" ? "join" : "company");
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);
  const id = useId();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const value = (name: string) => String(data.get(name) ?? "").trim();
    const checks: Record<string, Problem> = {
      ...(tab === "company" ? { company_name: checkRequired(value("company_name")) } : {}),
      full_name: checkRequired(value("full_name")),
      email: checkEmail(value("email")),
      password: checkNewPassword(String(data.get("password") ?? "")),
      ...(tab === "join" && !invite ? { company_code: checkRequired(value("company_code")) } : {}),
    };
    const problem = firstProblem(checks);
    setErrors(Object.fromEntries(Object.entries(checks).filter(([, p]) => p).map(([k, p]) => [k, problemText(t, p!)])));
    setError("");
    if (problem) return focusField(form, problem[0]);
    setBusy(true);
    if (tab === "company") {
      const result = await authCall<Me>("register", {
        company_name: value("company_name"), owner_name: value("full_name"), email: value("email"), password: data.get("password"),
      });
      setBusy(false);
      if (!result.ok) return setError(serverMessage(t, result.error));
      router.push(`/${lang}/app`);
      router.refresh();
      return;
    }
    const result = await authCall("join", {
      full_name: value("full_name"), email: value("email"), password: data.get("password"),
      ...(invite ? { invite_token: invite } : { company_code: value("company_code") }),
    });
    setBusy(false);
    if (!result.ok) return setError(serverMessage(t, result.error));
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
                id={`${id}-company`} onClick={() => { setTab("company"); setErrors({}); }}>{t.auth.tabCompany}</button>
        <button type="button" role="tab" aria-selected={tab === "join"} aria-controls={`${id}-panel`}
                id={`${id}-join`} onClick={() => { setTab("join"); setErrors({}); }}>{t.auth.tabJoin}</button>
      </div>
      <form id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`} onSubmit={submit} noValidate>
        {tab === "company" ? (
          <Field id={`${id}-company-name`} label={t.auth.companyName} name="company_name" autoComplete="organization"
                 required maxLength={120} error={errors.company_name} />
        ) : null}
        <Field id={`${id}-name`} label={t.auth.fullName} name="full_name" autoComplete="name" required maxLength={120} error={errors.full_name} />
        <Field id={`${id}-email`} label={t.auth.email} name="email" type="email" autoComplete="email" required error={errors.email} />
        <Field id={`${id}-password`} label={t.auth.password} name="password" type="password" autoComplete="new-password"
               required minLength={10} maxLength={128} hint={t.auth.passwordHint} error={errors.password} />
        {tab === "join" && !invite ? (
          <Field id={`${id}-code`} label={t.auth.companyCode} name="company_code" required minLength={4} maxLength={16}
                 autoCapitalize="characters" hint={t.auth.companyCodeHint} error={errors.company_code} />
        ) : null}
        {error ? <p className="error" role="alert">{error}</p> : null}
        <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: "100%" }}>
          {busy ? t.auth.working : tab === "company" ? t.auth.submitCompany : t.auth.submitJoin}
        </button>
        <p className="muted" style={{ marginTop: 16 }}>
          {t.auth.haveAccount} <Link className="link" href={`/${lang}/signin`}>{t.nav.signIn}</Link>
        </p>
      </form>
    </div>
  );
}

export function ForgotForm({ lang, t }: { lang: Locale; t: Dict }) {
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const id = useId();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const email = String(new FormData(form).get("email") ?? "").trim();
    const problem = checkEmail(email);
    setError(problem ? problemText(t, problem) : "");
    if (problem) return focusField(form, "email");
    setBusy(true);
    const result = await authCall("forgot", { email });
    setBusy(false);
    if (!result.ok) return setError(serverMessage(t, result.error));
    setSent(true);
  }

  if (sent) {
    return (
      <div>
        <p className="success" role="status">{t.auth.forgotSent}</p>
        <Link className="btn" href={`/${lang}/signin`}>{t.nav.signIn}</Link>
      </div>
    );
  }
  return (
    <form onSubmit={submit} noValidate>
      <Field id={`${id}-email`} label={t.auth.email} name="email" type="email" autoComplete="email" required error={error} />
      <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: "100%" }}>
        {busy ? t.auth.working : t.auth.sendLink}
      </button>
      <p className="muted" style={{ marginTop: 16 }}><Link className="link" href={`/${lang}/signin`}>{t.nav.signIn}</Link></p>
    </form>
  );
}

export function ResetForm({ lang, t }: { lang: Locale; t: Dict }) {
  const search = useSearchParams();
  const token = search.get("token") ?? "";
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const id = useId();

  if (token.length < 20) {
    return (
      <div>
        <p className="error" role="alert">{t.auth.resetMissing}</p>
        <Link className="btn" href={`/${lang}/forgot-password`}>{t.auth.askAgain}</Link>
      </div>
    );
  }
  if (done) {
    return (
      <div>
        <p className="success" role="status">{t.auth.resetDone}</p>
        <Link className="btn btn-primary" href={`/${lang}/signin`}>{t.nav.signIn}</Link>
      </div>
    );
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    const again = String(data.get("again") ?? "");
    const checks = { password: checkNewPassword(password), again: checkSame(password, again) };
    const problem = firstProblem(checks);
    setErrors(Object.fromEntries(Object.entries(checks).filter(([, p]) => p).map(([k, p]) => [k, problemText(t, p!)])));
    setError("");
    if (problem) return focusField(form, problem[0]);
    setBusy(true);
    const result = await authCall("reset", { token, new_password: password });
    setBusy(false);
    if (!result.ok) return setError(serverMessage(t, result.error));
    setDone(true);
  }

  return (
    <form onSubmit={submit} noValidate>
      <Field id={`${id}-password`} label={t.auth.newPassword} name="password" type="password" autoComplete="new-password"
             required minLength={10} maxLength={128} hint={t.auth.passwordHint} error={errors.password} />
      <Field id={`${id}-again`} label={t.auth.confirmPassword} name="again" type="password" autoComplete="new-password"
             required error={errors.again} />
      {error ? (
        <div role="alert">
          <p className="error">{error}</p>
          <p><Link className="link" href={`/${lang}/forgot-password`}>{t.auth.askAgain}</Link></p>
        </div>
      ) : null}
      <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: "100%" }}>
        {busy ? t.auth.working : t.auth.savePassword}
      </button>
    </form>
  );
}
