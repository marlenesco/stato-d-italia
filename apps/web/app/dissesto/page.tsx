import { Suspense } from "react";
import { DissestoWorkspace } from "../../components/dissesto-workspace";
import { SiteNav } from "../../components/site-nav";
import { loadDissestoData } from "../../lib/data";

export const revalidate = 60;

export default async function HydrogeologicalRiskPage() {
  try {
    const data = await loadDissestoData();
    return <main className="shell domain-shell"><SiteNav section="hydrogeological-risk" /><Suspense fallback={<section className="workspace-loading" aria-busy="true">Preparo l’atlante del dissesto…</section>}><DissestoWorkspace data={data} /></Suspense></main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="hydrogeological-risk" /><section className="page-intro"><h1>Dissesto</h1><p role="alert">Dati dissesto non ancora pubblicati nella release locale.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
