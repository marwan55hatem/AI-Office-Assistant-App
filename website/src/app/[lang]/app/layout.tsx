import type { Metadata } from "next";

import { AppShell } from "@/components/app-shell";
import { pageLocale } from "@/lib/page";

export const metadata: Metadata = { robots: { index: false } };

export default async function AppLayout({ children, params }: LayoutProps<"/[lang]/app">) {
  const { lang, t } = await pageLocale(params);
  return <AppShell lang={lang} t={t}>{children}</AppShell>;
}
