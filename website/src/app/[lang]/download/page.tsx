import type { Metadata } from "next";
import Link from "next/link";

import { DownloadCard } from "@/components/download-card";
import { PageTitle } from "@/components/site";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";
import { latestRelease } from "@/lib/server/release";

export async function generateMetadata({ params }: PageProps<"/[lang]/download">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).download.title, alternates: alternates(lang, "/download") } : {};
}

export default async function Download({ params }: PageProps<"/[lang]/download">) {
  const { lang, t } = await pageLocale(params);
  const d = t.download;
  const release = await latestRelease();
  return (
    <div className="container">
      <PageTitle title={d.title} lead={d.lead} />
      <div className="grid grid-2">
        <section className="card" aria-labelledby="release">
          <h2 id="release">{d.latest}</h2>
          <DownloadCard release={release} lang={lang} t={t} />
        </section>
        <section className="card" aria-labelledby="requirements">
          <h2 id="requirements">{d.requirementsTitle}</h2>
          <ul className="list">{d.requirements.map((item) => <li key={item}>{item}</li>)}</ul>
          <h3 style={{ marginTop: 20 }}>{d.stepsTitle}</h3>
          <ol className="list">{d.steps.map((step) => <li key={step}>{step}</li>)}</ol>
          <p className="muted">{d.after} <Link className="link" href={`/${lang}/signup`}>{t.home.ctaSignUp}</Link></p>
        </section>
      </div>
    </div>
  );
}
