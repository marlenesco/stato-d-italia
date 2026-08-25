import { SiteNav } from "../../../../components/site-nav";
import { TerritoryProfile } from "../../../../components/territory-profile";
import { loadRomeProfile } from "../../../../lib/data";

export const revalidate = 60;

export default async function RomeProfilePage() {
  try {
    const { profile, provenance, releaseId } = await loadRomeProfile();
    return <main className="shell"><SiteNav section="territory" /><TerritoryProfile profile={profile as never} /><details className="provenance"><summary>Fonte e provenance · release {releaseId}</summary><pre>{JSON.stringify(provenance, null, 2)}</pre></details></main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="territory" /><section className="page-intro"><h1>Roma</h1><p role="alert">Profilo non disponibile: configura CDN/R2 e pubblica release Milestone 5.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
