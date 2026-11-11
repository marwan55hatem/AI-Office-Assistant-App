import type { Metadata } from "next";
import { Suspense } from "react";

import { ResetForm } from "@/components/auth-forms";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/reset-password">): Promise<Metadata> {
  const { lang } = await params;
  // the link carries a secret token: never indexed, and no referrer leaves this page
  return hasLocale(lang) ? { title: getDictionary(lang).auth.resetTitle, robots: { index: false }, referrer: "no-referrer" } : {};
}

export default async function ResetPassword({ params }: PageProps<"/[lang]/reset-password">) {
  const { lang, t } = await pageLocale(params);
  return (
    <div className="narrow" style={{ maxWidth: 480 }}>
      <div className="page-title">
        <h1>{t.auth.resetTitle}</h1>
        <p className="lead">{t.auth.resetLead}</p>
      </div>
      <div className="card"><Suspense><ResetForm lang={lang} t={t} /></Suspense></div>
    </div>
  );
}
