import { notFound } from "next/navigation";
import { SiteNav } from "../../../../components/site-nav";
import { TerritoryProfile } from "../../../../components/territory-profile";
import { loadTerritoryProfile } from "../../../../lib/data";

export const revalidate = 60;

const levels = { comuni: "municipality", province: "province", regioni: "region" } as const;

export default async function TerritoryPage({ params }: { params: Promise<{ level: string; istatCode: string }> }) {
  const { level: routeLevel, istatCode } = await params;
  const level = levels[routeLevel as keyof typeof levels];
  if (!level) notFound();

  try {
    const { profile, provenance, releaseId, insights } = await loadTerritoryProfile(level, istatCode);
    return <main className="shell territory-shell"><SiteNav section="territory" /><TerritoryProfile profile={profile} insights={insights} /><details className="provenance territory-provenance"><summary>Fonte e provenance · release {releaseId}</summary><pre>{JSON.stringify(provenance, null, 2)}</pre></details></main>;
  } catch {
    notFound();
  }
}
