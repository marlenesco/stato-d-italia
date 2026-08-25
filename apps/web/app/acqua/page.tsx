import { SiteNav } from "../../components/site-nav";
import { ThemeWorkspace } from "../../components/soil-workspace";
import { loadWaterData } from "../../lib/data";

export const revalidate = 60;

export default async function WaterPage() {
  try {
    const data = await loadWaterData();
    return <main className="shell"><SiteNav section="water" /><section className="page-intro"><p className="eyebrow">ISPRA BIGBANG 10.0 · release {data.releaseId}</p><h1>Risorsa idrica</h1><p>Stime ufficiali BIGBANG per Italia e Regioni. Province e Comuni arriveranno come elaborazioni dichiarate da raster.</p></section><Suspense fallback={<section className="workspace-loading" aria-busy="true">Preparo l’esploratore…</section>}><ThemeWorkspace data={data} themeLabel="risorsa idrica" /></Suspense></main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="water" /><section className="page-intro"><h1>Risorsa idrica</h1><p role="alert">Dati acqua non ancora pubblicati nella release CDN.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
import { Suspense } from "react";
