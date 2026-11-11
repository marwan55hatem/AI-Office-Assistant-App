import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import { notFound } from "next/navigation";

import "../globals.css";
import { Backdrop } from "@/components/backdrop";
import { SiteFooter, SiteHeader } from "@/components/site";
import { fontVariables } from "@/lib/fonts";
import { dir, getDictionary, hasLocale, locales } from "@/lib/i18n";

export function generateStaticParams() {
  return locales.map((lang) => ({ lang }));
}

export const viewport: Viewport = {
  themeColor: [{ media: "(prefers-color-scheme: dark)", color: "#050508" }, { media: "(prefers-color-scheme: light)", color: "#f6f7fb" }],
};

export async function generateMetadata({ params }: LayoutProps<"/[lang]">): Promise<Metadata> {
  const { lang } = await params;
  if (!hasLocale(lang)) return {};
  const t = getDictionary(lang);
  return {
    metadataBase: new URL(process.env.SITE_URL ?? "http://localhost:3100"),
    title: { default: t.meta.title, template: `%s · ${t.nav.brand}` },
    description: t.meta.description,
    openGraph: {
      title: t.meta.title, description: t.meta.description, locale: lang === "ar" ? "ar" : "en", type: "website",
      siteName: t.nav.brand, images: [{ url: "/og.png", width: 1200, height: 630, alt: t.meta.title }],
    },
    twitter: { card: "summary_large_image", title: t.meta.title, description: t.meta.description, images: ["/og.png"] },
  };
}

/** Sets the theme before the first paint (no flash): the saved choice, else the system setting.
 *  Also pauses the animations while the tab is hidden. */
const BOOT_SCRIPT = `try{var t=localStorage.getItem("oa-theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="dark"}document.addEventListener("visibilitychange",function(){document.documentElement.classList.toggle("motion-paused",document.hidden)});`;

export default async function RootLayout({ children, params }: LayoutProps<"/[lang]">) {
  const { lang } = await params;
  if (!hasLocale(lang)) notFound();
  const t = getDictionary(lang);
  const signedIn = (await cookies()).has("oa_rt");
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang={lang} dir={dir(lang)} className={fontVariables} suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: BOOT_SCRIPT }} />
      </head>
      <body>
        <a className="skip" href="#main">{t.nav.skip}</a>
        <div className="page">
          <Backdrop />
          <SiteHeader lang={lang} t={t} signedIn={signedIn} />
          <main id="main">{children}</main>
          <SiteFooter t={t} />
        </div>
      </body>
    </html>
  );
}
