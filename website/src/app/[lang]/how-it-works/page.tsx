import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { PageTitle } from "@/components/site";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/how-it-works">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).how.title, alternates: alternates(lang, "/how-it-works") } : {};
}

export default async function HowItWorks({ params }: PageProps<"/[lang]/how-it-works">) {
  const { lang, t } = await pageLocale(params);
  return (
    <div className="container">
      <PageTitle title={t.how.title} lead={t.how.lead} />
      <ol className="steps" style={{ listStyle: "none", padding: 0 }}>
        {t.how.steps.map((step, index) => (
          <li key={step.title} className="step">
            <div>
              <span className="step-num" aria-hidden="true">{index + 1}</span>
              <h2>{step.title}</h2>
              <p className="muted">{step.text}</p>
              {index === 1 ? (
                <div className="actions">
                  <Link className="btn btn-primary" href={`/${lang}/signup`}>{t.nav.signUp}</Link>
                </div>
              ) : null}
              {index === 0 ? (
                <div className="actions">
                  <Link className="btn" href={`/${lang}/download`}>{t.nav.download}</Link>
                </div>
              ) : null}
            </div>
            {step.shot ? (
              <Image className="shot" src={`/screens/${step.shot}`} alt={step.alt} width={1280} height={800}
                     sizes="(max-width: 900px) 100vw, 600px" />
            ) : <div />}
          </li>
        ))}
      </ol>
    </div>
  );
}
