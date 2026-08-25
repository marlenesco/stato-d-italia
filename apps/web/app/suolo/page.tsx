import { SiteNav } from "../../components/site-nav";
import { ThemeWorkspace } from "../../components/soil-workspace";
import { loadSoilData } from "../../lib/data";

export const revalidate = 60;

export default async function SoilPage() {
  try {
    const data = await loadSoilData();
    return <main className="shell">
      <SiteNav section="soil" />
      <section className="page-intro"><p className="eyebrow">ISPRA / SNPA · release {data.releaseId}</p><h1>Consumo di suolo</h1><p>Valori ufficiali per periodo. Analisi, ranking e percentili sono elaborazioni riproducibili del progetto.</p></section>
      <ThemeWorkspace data={data} themeLabel="consumo di suolo" />
    </main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="soil" /><section className="page-intro"><h1>Consumo di suolo</h1><p role="alert">Dati CDN non configurati o release non ancora pubblicata.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
