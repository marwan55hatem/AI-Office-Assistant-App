import type { Metadata } from "next";
import { Suspense } from "react";

import { SignInForm } from "@/components/auth-forms";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/signin">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).auth.signInTitle, alternates: alternates(lang, "/signin"), robots: { index: false } } : {};
}

export default async function SignIn({ params }: PageProps<"/[lang]/signin">) {
  const { lang, t } = await pageLocale(params);
  return (
    <div className="narrow" style={{ maxWidth: 480 }}>
      <div className="page-title">
        <h1>{t.auth.signInTitle}</h1>
        <p className="lead">{t.auth.signInLead}</p>
      </div>
      <div className="card">
        <Suspense>
          <SignInForm lang={lang} t={t} />
        </Suspense>
      </div>
    </div>
  );
}
