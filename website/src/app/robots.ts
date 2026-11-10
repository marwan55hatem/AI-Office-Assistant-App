import type { MetadataRoute } from "next";

const SITE = process.env.SITE_URL ?? "http://localhost:3100";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/en/app", "/ar/app"] },
    sitemap: `${SITE}/sitemap.xml`,
  };
}
