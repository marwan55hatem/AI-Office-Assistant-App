import type { Metadata } from "next";

import { PageTitle, REPO } from "@/components/site";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/faq">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).faq.title, alternates: alternates(lang, "/faq") } : {};
}

export default async function Faq({ params }: PageProps<"/[lang]/faq">) {
  const { t } = await pageLocale(params);
  return (
    <div className="narrow">
      <PageTitle title={t.faq.title} lead={t.faq.lead} />
      {t.faq.items.map((item) => (
        <details key={item.q}>
          <summary>{item.q}</summary>
          <p className="muted" style={{ marginTop: 10 }}>{item.a}</p>
        </details>
      ))}
      <section className="section">
        <h2>{t.faq.guides}</h2>
        <ul className="list">
          {t.faq.guideLinks.map((link) => (
            <li key={link.path}>
              <a href={`${REPO}/blob/main/${link.path}`} rel="noopener">{link.label}</a>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
