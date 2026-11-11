import "server-only";

import type { Release } from "@/lib/release-types";

export const REPO_SLUG = process.env.GITHUB_REPO ?? "marwan55hatem/AI-Office-Assistant-App";

type GitHubRelease = {
  tag_name: string;
  published_at: string;
  html_url: string;
  assets: { name: string; size: number; browser_download_url: string }[];
};

/**
 * The latest release, cached for an hour (GitHub allows 60 anonymous calls an hour per address;
 * GITHUB_TOKEN raises that).
 * - a Release when one is published (DOWNLOAD_URL, if set, replaces the installer link);
 * - null when there is no release yet (GitHub answers 404) and no DOWNLOAD_URL;
 * - "unavailable" when GitHub cannot be reached.
 */
export async function latestRelease(): Promise<Release | null | "unavailable"> {
  const configured = process.env.DOWNLOAD_URL || null;
  const headers: Record<string, string> = { accept: "application/vnd.github+json", "user-agent": "office-assistant-website" };
  if (process.env.GITHUB_TOKEN) headers.authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  let response: Response;
  try {
    response = await fetch(`https://api.github.com/repos/${REPO_SLUG}/releases/latest`, {
      headers, next: { revalidate: 3600 }, signal: AbortSignal.timeout(6000),
    });
  } catch {
    return configured ? manual(configured) : "unavailable";
  }
  if (response.status === 404) return configured ? manual(configured) : null;
  if (!response.ok) return configured ? manual(configured) : "unavailable";
  const data = (await response.json()) as GitHubRelease;
  const assets = data.assets
    .map((a) => ({ name: a.name, size: a.size, url: a.browser_download_url }))
    // the setup program first, then its data parts in order
    .sort((a, b) => Number(b.name.endsWith(".exe")) - Number(a.name.endsWith(".exe")) || a.name.localeCompare(b.name));
  const installer = configured ?? assets.find((a) => a.name.toLowerCase().endsWith(".exe"))?.url ?? null;
  if (!installer) return null;
  return { version: data.tag_name, published: data.published_at, url: data.html_url, installerUrl: installer, assets };
}

function manual(url: string): Release {
  return { version: "", published: new Date().toISOString(), url: `https://github.com/${REPO_SLUG}/releases`, installerUrl: url, assets: [] };
}
