import "server-only";

export const REPO_SLUG = "marwan55hatem/AI-Office-Assistant-App";

export type Asset = { name: string; size: number; url: string };
export type Release = { version: string; published: string; url: string; assets: Asset[] };

type GitHubRelease = {
  tag_name: string;
  published_at: string;
  html_url: string;
  assets: { name: string; size: number; browser_download_url: string }[];
};

/**
 * The latest GitHub release, cached for an hour (GitHub allows 60 anonymous calls an hour
 * per address; set GITHUB_TOKEN to raise that). Returns null when GitHub cannot be reached,
 * and the page then links to the releases page instead.
 */
export async function latestRelease(): Promise<Release | null> {
  const headers: Record<string, string> = { accept: "application/vnd.github+json", "user-agent": "office-assistant-website" };
  if (process.env.GITHUB_TOKEN) headers.authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  try {
    const response = await fetch(`https://api.github.com/repos/${REPO_SLUG}/releases/latest`, {
      headers,
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(6000),
    });
    if (!response.ok) return null;
    const data = (await response.json()) as GitHubRelease;
    return {
      version: data.tag_name,
      published: data.published_at,
      url: data.html_url,
      // the setup program first, then its data parts in order
      assets: data.assets
        .map((a) => ({ name: a.name, size: a.size, url: a.browser_download_url }))
        .sort((a, b) => Number(b.name.endsWith(".exe")) - Number(a.name.endsWith(".exe")) || a.name.localeCompare(b.name)),
    };
  } catch {
    return null;
  }
}

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
