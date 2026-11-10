import type { MetadataRoute } from "next";

const SITE = process.env.SITE_URL ?? "http://localhost:3100";
const PATHS = ["", "/how-it-works", "/features", "/privacy", "/download", "/faq", "/signup"];

export default function sitemap(): MetadataRoute.Sitemap {
  return PATHS.map((path) => ({
    url: `${SITE}/en${path}`,
    alternates: { languages: { en: `${SITE}/en${path}`, ar: `${SITE}/ar${path}` } },
  }));
}
