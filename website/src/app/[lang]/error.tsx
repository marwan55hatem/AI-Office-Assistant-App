"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { getDictionary, hasLocale } from "@/lib/i18n";

/** Shown when a page fails to render; nothing about the error itself is shown to the visitor. */
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const params = useParams<{ lang: string }>();
  const lang = params?.lang && hasLocale(params.lang) ? params.lang : "en";
  const t = getDictionary(lang);
  return (
    <div className="container error-page" role="alert">
      <p className="code" aria-hidden="true">!</p>
      <h1 className="head">{t.errors.errorTitle}</h1>
      <p className="lead">{t.errors.errorText}</p>
      <div className="actions" style={{ justifyContent: "center" }}>
        <button className="btn btn-primary" type="button" onClick={reset}>{t.errors.retry}</button>
        <Link className="btn" href={`/${lang}`}>{t.errors.home}</Link>
      </div>
    </div>
  );
}
