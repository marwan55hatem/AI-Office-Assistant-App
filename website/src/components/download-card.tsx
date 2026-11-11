import { DownloadIcon, External, GitHubIcon, REPO } from "@/components/site";
import type { Dict, Locale } from "@/lib/i18n";
import type { Release } from "@/lib/release-types";

export function formatSize(bytes: number, locale: string): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const number = new Intl.NumberFormat(locale === "ar" ? "ar-u-nu-latn" : "en", { maximumFractionDigits: unit >= 3 ? 2 : 1 });
  return `${number.format(value)} ${units[unit]}`;
}

/**
 * The installer download: version, date, total size, the installer button and every file.
 * `release` is null when there is no published release (the button is then disabled with a
 * reason) and "unavailable" when GitHub could not be reached (a link to the releases page instead).
 */
export function DownloadCard({ release, lang, t, compact = false }: {
  release: Release | null | "unavailable"; lang: Locale; t: Dict; compact?: boolean;
}) {
  const d = t.download;
  if (release === "unavailable") {
    return (
      <div data-testid="download-card">
        <p>{d.unavailable} {d.unavailableHint}</p>
        <External href={`${REPO}/releases`} className="btn" t={t}><GitHubIcon />{d.github}</External>
      </div>
    );
  }
  if (release === null) {
    return (
      <div data-testid="download-card">
        <p className="muted" id="no-release">{d.noRelease} {d.noReleaseHint}</p>
        <div className="actions" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" type="button" disabled aria-describedby="no-release"><DownloadIcon />{d.button}</button>
          <External href={REPO} className="btn" t={t}><GitHubIcon />{d.github}</External>
        </div>
      </div>
    );
  }
  const total = release.assets.reduce((sum, a) => sum + a.size, 0);
  const date = new Intl.DateTimeFormat(lang === "ar" ? "ar-u-nu-latn" : "en", { dateStyle: "long" }).format(new Date(release.published));
  return (
    <div data-testid="download-card">
      <dl className="kv">
        <dt>{d.latest}</dt><dd data-testid="version" dir="ltr" style={{ textAlign: "start" }}>{release.version}</dd>
        <dt>{d.published}</dt><dd>{date}</dd>
        {total ? <><dt>{d.total}</dt><dd data-testid="total-size" dir="ltr" style={{ textAlign: "start" }}>{formatSize(total, lang)}</dd></> : null}
      </dl>
      <div className="actions" style={{ marginTop: 0 }}>
        <a className="btn btn-primary" href={release.installerUrl}><DownloadIcon />{d.button}</a>
        <External href={release.url} className="btn" t={t}><GitHubIcon />{d.github}</External>
      </div>
      {!compact && release.assets.length ? (
        <>
          <h3 style={{ marginTop: 24 }}>{d.files}</h3>
          <ul className="list" data-testid="assets">
            {release.assets.map((asset) => (
              <li key={asset.name}>
                <a className="link" href={asset.url} dir="ltr">{asset.name}</a> <span className="muted">({formatSize(asset.size, lang)})</span>
              </li>
            ))}
          </ul>
          {release.assets.length > 1 ? <p className="hint">{d.multipart}</p> : null}
        </>
      ) : null}
    </div>
  );
}
