import type { Metadata } from "next";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import "../globals.css";
import { SiteFooter, SiteHeader } from "@/components/site";
import { dir, getDictionary, hasLocale, locales } from "@/lib/i18n";

export function generateStaticParams() {
  return locales.map((lang) => ({ lang }));
}

export async function generateMetadata({ params }: LayoutProps<"/[lang]">): Promise<Metadata> {
  const { lang } = await params;
  if (!hasLocale(lang)) return {};
  const t = getDictionary(lang);
  return {
    metadataBase: new URL(process.env.SITE_URL ?? "http://localhost:3100"),
    title: { default: t.meta.title, template: `%s · Office Assistant` },
    description: t.meta.description,
    openGraph: { title: t.meta.title, description: t.meta.description, locale: lang === "ar" ? "ar" : "en", type: "website" },
  };
}

/** Sets the saved theme before the first paint (no flash), defaulting to the system setting. */
const THEME_SCRIPT = `try{var t=localStorage.getItem("oa-theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){}`;

export default async function RootLayout({ children, params }: LayoutProps<"/[lang]">) {
  const { lang } = await params;
  if (!hasLocale(lang)) notFound();
  const t = getDictionary(lang);
  const signedIn = (await cookies()).has("oa_rt");
  return (
    <html lang={lang} dir={dir(lang)} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <a className="skip" href="#main">{t.nav.skip}</a>
        <SiteHeader lang={lang} t={t} signedIn={signedIn} />
        <main id="main">{children}</main>
        <SiteFooter t={t} />
      </body>
    </html>
  );
}
