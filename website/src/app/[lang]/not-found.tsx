"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { getDictionary, hasLocale } from "@/lib/i18n";

export default function NotFound() {
  const params = useParams<{ lang: string }>();
  const lang = params?.lang && hasLocale(params.lang) ? params.lang : "en";
  const t = getDictionary(lang);
  return (
    <div className="container error-page">
      <p className="code" aria-hidden="true">404</p>
      <h1 className="head">{t.errors.notFoundTitle}</h1>
      <p className="lead">{t.errors.notFoundText}</p>
      <div className="actions" style={{ justifyContent: "center" }}>
        <Link className="btn btn-primary" href={`/${lang}`}>{t.errors.home}</Link>
      </div>
    </div>
  );
}
