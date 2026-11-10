import { notFound } from "next/navigation";

import { getDictionary, hasLocale, type Dict, type Locale } from "@/lib/i18n";

/** The page's language and texts from its route parameters (404 for an unknown language). */
export async function pageLocale(params: Promise<{ lang: string }>): Promise<{ lang: Locale; t: Dict }> {
  const { lang } = await params;
  if (!hasLocale(lang)) notFound();
  return { lang, t: getDictionary(lang) };
}

/** The page's canonical address and its other-language twin (for search engines). */
export function alternates(lang: Locale, path: string) {
  return { canonical: `/${lang}${path}`, languages: { en: `/en${path}`, ar: `/ar${path}`, "x-default": `/en${path}` } };
}
