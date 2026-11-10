import type { Metadata } from "next";

import { PageTitle } from "@/components/site";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/privacy">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).privacy.title, alternates: alternates(lang, "/privacy") } : {};
}

export default async function Privacy({ params }: PageProps<"/[lang]/privacy">) {
  const { t } = await pageLocale(params);
  const p = t.privacy;
  return (
    <div className="container">
      <PageTitle title={p.title} lead={p.lead} />
      <div className="grid grid-2">
        <section className="card">
          <h2>{p.localTitle}</h2>
          <ul className="list">{p.local.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
        <section className="card">
          <h2>{p.onlineTitle}</h2>
          <ul className="list">{p.online.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      </div>
      <div className="grid grid-2 section">
        <section>
          <h2>{p.aiTitle}</h2>
          <p>{p.ai}</p>
        </section>
        <section>
          <h2>{p.emailTitle}</h2>
          <p>{p.email}</p>
        </section>
      </div>
      <p className="callout">{p.contact}</p>
    </div>
  );
}
