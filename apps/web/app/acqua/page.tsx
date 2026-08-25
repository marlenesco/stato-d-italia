import { Suspense } from "react";
import { SiteNav } from "../../components/site-nav";
import { WaterWorkspace } from "../../components/water-workspace";
import { loadWaterData, loadWaterOverview } from "../../lib/data";

export const revalidate = 60;

export default async function WaterPage() {
  try {
    const [data, overview] = await Promise.all([loadWaterData(), loadWaterOverview()]);
    return <main className="shell water-shell"><SiteNav section="water" /><Suspense fallback={<section className="workspace-loading" aria-busy="true">Preparo l’atlante idrico…</section>}><WaterWorkspace data={data} overview={overview} /></Suspense></main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="water" /><section className="page-intro"><h1>Risorsa idrica</h1><p role="alert">Dati acqua non ancora pubblicati nella release CDN.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
