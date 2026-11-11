import type { Metadata } from "next";

import { ForgotForm } from "@/components/auth-forms";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/forgot-password">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang)
    ? { title: getDictionary(lang).auth.forgotTitle, alternates: alternates(lang, "/forgot-password"), robots: { index: false } }
    : {};
}

export default async function ForgotPassword({ params }: PageProps<"/[lang]/forgot-password">) {
  const { lang, t } = await pageLocale(params);
  return (
    <div className="narrow" style={{ maxWidth: 480 }}>
      <div className="page-title">
        <h1>{t.auth.forgotTitle}</h1>
        <p className="lead">{t.auth.forgotLead}</p>
      </div>
      <div className="card"><ForgotForm lang={lang} t={t} /></div>
    </div>
  );
}
