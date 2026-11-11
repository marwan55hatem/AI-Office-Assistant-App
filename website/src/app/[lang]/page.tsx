import type { Metadata } from "next";
import Link from "next/link";

import { DownloadIcon, External, GitHubIcon, REPO } from "@/components/site";
import { hasLocale } from "@/lib/i18n";
import { alternates, pageLocale } from "@/lib/page";

export async function generateMetadata({ params }: PageProps<"/[lang]">): Promise<Metadata> {
  const { lang } = await params;
  return hasLocale(lang) ? { alternates: alternates(lang, "") } : {};
}

/** Icon paths of the six feature cards (from the design). */
const FEATURE_ICONS = [
  "M3 7h4l2-3h6l2 3h4v12H3zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  "M7 3h10v18H7zM11 18h2",
  "M6 3h9l4 4v14H6zM9 12h7M9 16h7",
  "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  "M4 5h16v11H9l-5 4z",
  "M4 20V10M10 20V4M16 20v-8M22 20H2",
];
const FEATURE_SPANS = [4, 2, 2, 2, 2, 6];
const FEATURE_ICON_BG = ["#e1e7ff", "#ffe0ef", "#ffeecb", "#d6f6ea", "#e1e7ff", "#ffe0ef"];   // light theme only
const BARS: [number, string][] = [[58, "a"], [76, "a"], [50, "a"], [92, "b"], [70, "a"], [28, "c"], [20, "c"]];
const FEED_TONES = ["good", "info", "warn", "good", "bad", "sync"];
const TILE_TIMES = ["01:06:12", "00:11:40", "00:06:44"];

export default async function Home({ params }: PageProps<"/[lang]">) {
  const { lang, t } = await pageLocale(params);
  const h = t.home;
  return (
    <div className="container">
      {/* hero */}
      <section className="hero" aria-labelledby="hero-title">
        <div className="pill"><span><i className="live-dot" aria-hidden="true" />{h.pill}</span></div>
        <h1 id="hero-title" className="head">{h.titleA}<br /><span className="acc">{h.titleB}</span></h1>
        <p className="lead">{h.lead}</p>
        <div className="actions">
          <Link className="btn btn-primary" href={`/${lang}/download`}><DownloadIcon />{h.ctaDownload}</Link>
          <External href={REPO} className="btn" t={t}><GitHubIcon />{h.ctaGithub}</External>
        </div>
      </section>

      {/* the manager-report mock (example data) */}
      <figure className="beam mock" style={{ margin: "0 auto 120px" }}>
        <div className="beam-inner" role="img" aria-label={h.mockLabel}>
          <div className="mock-bar">
            <i style={{ background: "#ff5f57" }} /><i style={{ background: "#febc2e" }} /><i style={{ background: "#28c840" }} />
            <span className="mock-path">{h.mockPath}</span>
            <span className="mock-note">{h.example}</span>
          </div>
          <div className="mock-grid">
            <div className="mock-chart">
              <div className="mock-chart-head"><span>{h.mockTitle}</span><span>{h.mockRange}</span></div>
              <div className="bars">
                {BARS.map(([height, tone], i) => (
                  <div key={i} style={{ height: `${height}%`, background: `var(--bar-${tone})`, animationDelay: `${-0.6 * i}s` }} />
                ))}
              </div>
              <div className="bar-days">{h.mockDays.map((d) => <span key={d}>{d}</span>)}</div>
            </div>
            <div className="tiles">
              {(["focus", "dist", "away"] as const).map((tile, i) => (
                <div key={tile} className={`tile tile-${tile}`}>
                  <b>{[h.focus, h.distracted, h.away][i]}</b><span>{TILE_TIMES[i]}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </figure>

      {/* features: the bento grid */}
      <section id="features" className="block" aria-labelledby="features-title">
        <div className="section-head">
          <p className="eyebrow">{h.featuresEyebrow}</p>
          <h2 id="features-title" className="head">{h.featuresTitleA}<br />{h.featuresTitleB}</h2>
        </div>
        <div className="bento">
          {h.features.map((feature, i) => (
            <article key={feature.title} className={`beam span-${FEATURE_SPANS[i]}`}>
              <div className="beam-inner">
                <div className="num-label">{String(i + 1).padStart(2, "0")}</div>
                <div className="icon-box" style={{ ["--light-icon-bg" as string]: FEATURE_ICON_BG[i] }}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={FEATURE_ICONS[i]} />
                  </svg>
                </div>
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* live activity */}
      <section id="live" className="block live-row" aria-labelledby="live-title">
        <div>
          <p className="eyebrow alt">{h.liveEyebrow}</p>
          <h2 id="live-title" className="head">{h.liveTitle}</h2>
          <p className="lead">{h.liveText}</p>
        </div>
        <figure className="beam" style={{ margin: 0 }}>
          <div className="beam-inner" style={{ padding: 22 }}>
            <div className="feed" role="img" aria-label={`${h.feedLabel}: ${h.feed.join(", ")}`}>
              <div className="feed-in" aria-hidden="true">
                {[...h.feed, ...h.feed].map((event, i) => (
                  <div key={i} className={`feed-item feed-${FEED_TONES[i % FEED_TONES.length]}`}>● {event}</div>
                ))}
              </div>
            </div>
            <figcaption className="illustrative">{h.example}</figcaption>
          </div>
        </figure>
      </section>

      {/* how it works */}
      <section id="how" className="block" aria-labelledby="how-title">
        <div className="section-head">
          <p className="eyebrow">{h.howEyebrow}</p>
          <h2 id="how-title" className="head">{h.howTitle}</h2>
        </div>
        <ol className="steps-row" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {h.steps.map((step, i) => (
            <li key={step.title} className="beam">
              <div className="beam-inner">
                <div className="step-n" aria-hidden="true">{String(i + 1).padStart(2, "0")}</div>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* privacy strip */}
      <section className="block" aria-label={h.privacyLabel}>
        <ul className="privacy-strip" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {h.privacy.map((item) => (
            <li key={item} className="privacy-item">
              <svg className="shield" width="22" height="22" viewBox="0 0 24 24" fill="none" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" />
              </svg>
              <div>{item}</div>
            </li>
          ))}
        </ul>
        <p style={{ textAlign: "center", marginTop: 24 }}><Link className="link" href={`/${lang}/privacy`}>{t.nav.privacy}</Link></p>
      </section>

      {/* call to action */}
      <section id="download" className="beam cta block" aria-labelledby="cta-title" style={{ marginBottom: 80 }}>
        <div className="beam-inner">
          <div className="cta-blob" aria-hidden="true" style={{ width: 420, height: 420, insetInlineStart: -80, top: -140, background: "#3b5bff", opacity: 0.5 }} />
          <div className="cta-blob" aria-hidden="true" style={{ width: 380, height: 380, insetInlineEnd: -60, bottom: -150, background: "#d946a8", opacity: 0.45 }} />
          <div style={{ position: "relative" }}>
            <h2 id="cta-title">{h.ctaTitle}</h2>
            <p>{h.ctaText}</p>
            <div className="actions">
              <Link className="btn btn-primary" href={`/${lang}/signup`}>{h.ctaCompany}</Link>
              <Link className="btn btn-accent" href={`/${lang}/download`}><DownloadIcon />{h.ctaDownload}</Link>
              <Link className="btn btn-ghost" href={`/${lang}/signin`}>{h.ctaSignIn}</Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
