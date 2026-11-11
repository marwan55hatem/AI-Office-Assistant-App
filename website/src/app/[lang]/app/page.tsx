import { DownloadCard } from "@/components/download-card";
import { OverviewView } from "@/components/views/overview";
import { pageLocale } from "@/lib/page";
import { latestRelease } from "@/lib/server/release";

export default async function AppOverview({ params }: PageProps<"/[lang]/app">) {
  const { lang, t } = await pageLocale(params);
  const release = await latestRelease();
  return <OverviewView download={<DownloadCard release={release} lang={lang} t={t} compact />} />;
}
