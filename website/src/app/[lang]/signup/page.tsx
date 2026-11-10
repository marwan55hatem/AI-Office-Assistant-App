import type { Metadata } from "next";
import { Suspense } from "react";

import { SignUpForm } from "@/components/auth-forms";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/signup">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).auth.signUpTitle, alternates: alternates(lang, "/signup") } : {};
}

export default async function SignUp({ params }: PageProps<"/[lang]/signup">) {
  const { lang, t } = await pageLocale(params);
  return (
    <div className="narrow" style={{ maxWidth: 520 }}>
      <div className="page-title">
        <h1>{t.auth.signUpTitle}</h1>
        <p className="lead">{t.auth.signUpLead}</p>
      </div>
      <div className="card">
        <Suspense>
          <SignUpForm lang={lang} t={t} />
        </Suspense>
      </div>
    </div>
  );
}
