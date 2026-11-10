import type { Metadata } from "next";
import Image from "next/image";

import { PageTitle } from "@/components/site";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]/features">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).features.title, alternates: alternates(lang, "/features") } : {};
}

const SHOTS = ["phase4_reports_team_light.png", "phase6_meetings_manager_light.png", "phase7_messages_manager_light.png"];

export default async function Features({ params }: PageProps<"/[lang]/features">) {
  const { t } = await pageLocale(params);
  return (
    <div className="container">
      <PageTitle title={t.features.title} lead={t.features.lead} />
      <div className="grid grid-3">
        {t.features.groups.map((group) => (
          <section key={group.title} className="card">
            <h2>{group.title}</h2>
            <ul className="list">
              {group.items.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </section>
        ))}
      </div>
      <div className="grid grid-3 section">
        {SHOTS.map((shot, i) => (
          <Image key={shot} className="shot" src={`/screens/${shot}`} width={1440} height={900}
                 alt={[t.app.nav.dashboard, t.app.nav.meetings, t.app.nav.messages][i]}
                 sizes="(max-width: 900px) 100vw, 360px" />
        ))}
      </div>
    </div>
  );
}
