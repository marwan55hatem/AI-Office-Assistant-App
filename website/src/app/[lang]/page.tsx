import Image from "next/image";
import Link from "next/link";

import type { Metadata } from "next";

import { hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { alternates: alternates(lang, "") } : {};
}

export default async function Home({ params }: PageProps<"/[lang]">) {
  const { lang, t } = await pageLocale(params);
  const h = t.home;
  return (
    <div className="container">
      <section className="hero">
        <div>
          <p className="eyebrow">{h.eyebrow}</p>
          <h1>{h.title}</h1>
          <p className="lead">{h.lead}</p>
          <div className="actions">
            <Link className="btn btn-primary" href={`/${lang}/download`}>{h.ctaDownload}</Link>
            <Link className="btn" href={`/${lang}/signup`}>{h.ctaSignUp}</Link>
          </div>
        </div>
        <Image className="shot" src="/screens/1280x800_employee_session_dark.png" alt={h.shotAlt}
               width={1280} height={800} priority sizes="(max-width: 900px) 100vw, 540px" />
      </section>

      <section className="section" aria-labelledby="highlights">
        <h2 id="highlights" className="sr-only">{t.nav.features}</h2>
        <div className="grid grid-3">
          {h.highlights.map((item) => (
            <article key={item.title} className="card">
              <h3>{item.title}</h3>
              <p className="muted">{item.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="callout">
          <h2>{h.privacyTitle}</h2>
          <p>{h.privacyText}</p>
          <Link href={`/${lang}/privacy`}>{h.privacyLink}</Link>
        </div>
      </section>
    </div>
  );
}
