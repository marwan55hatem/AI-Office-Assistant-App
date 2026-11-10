import type { Metadata } from "next";
import Link from "next/link";

import { PageTitle, REPO } from "@/components/site";
import { getDictionary, hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";
import { formatSize, latestRelease } from "@/lib/server/release";

export async function generateMetadata({ params }: PageProps<"/[lang]/download">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { title: getDictionary(lang).download.title, alternates: alternates(lang, "/download") } : {};
}

export default async function Download({ params }: PageProps<"/[lang]/download">) {
  const { lang, t } = await pageLocale(params);
  const d = t.download;
  const release = await latestRelease();
  const setup = release?.assets.find((a) => a.name.toLowerCase().endsWith(".exe"));
  const total = release?.assets.reduce((sum, a) => sum + a.size, 0) ?? 0;
  const date = release
    ? new Intl.DateTimeFormat(lang === "ar" ? "ar-u-nu-latn" : "en", { dateStyle: "long" }).format(new Date(release.published))
    : "";

  return (
    <div className="container">
      <PageTitle title={d.title} lead={d.lead} />
      <div className="grid grid-2">
        <section className="card" aria-labelledby="release">
          {release ? (
            <>
              <h2 id="release">{d.latest}: <span data-testid="version">{release.version}</span></h2>
              <dl className="kv">
                <dt>{d.published}</dt><dd>{date}</dd>
                <dt>{d.total}</dt><dd data-testid="total-size">{formatSize(total, lang)}</dd>
              </dl>
              <div className="actions" style={{ marginTop: 0 }}>
                {setup ? <a className="btn btn-primary" href={setup.url}>{d.button}</a> : null}
                <a className="btn" href={release.url} rel="noopener">{d.github}</a>
              </div>
              <h3 style={{ marginTop: 24 }}>{d.files}</h3>
              <ul className="list" data-testid="assets">
                {release.assets.map((asset) => (
                  <li key={asset.name}>
                    <a href={asset.url}>{asset.name}</a> <span className="muted">({formatSize(asset.size, lang)})</span>
                  </li>
                ))}
              </ul>
              {release.assets.length > 1 ? <p className="hint">{d.multipart}</p> : null}
            </>
          ) : (
            <>
              <h2 id="release">{d.latest}</h2>
              <p>{d.unavailable} {d.unavailableHint}</p>
              <a className="btn btn-primary" href={`${REPO}/releases`} rel="noopener">{d.github}</a>
            </>
          )}
        </section>
        <section className="card" aria-labelledby="requirements">
          <h2 id="requirements">{d.requirementsTitle}</h2>
          <ul className="list">{d.requirements.map((item) => <li key={item}>{item}</li>)}</ul>
          <h3 style={{ marginTop: 20 }}>{d.afterTitle}</h3>
          <p className="muted">{d.after}</p>
          <Link href={`/${lang}/signup`}>{t.home.ctaSignUp}</Link>
        </section>
      </div>
    </div>
  );
}
