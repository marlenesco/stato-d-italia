import { SiteNav } from "../../components/site-nav";
import { ThemeWorkspace } from "../../components/soil-workspace";
import { loadSoilData } from "../../lib/data";

export const revalidate = 60;

export default async function SoilPage() {
  try {
    const data = await loadSoilData();
    return <main className="shell soil-shell">
      <SiteNav section="soil" />
      <Suspense fallback={<section className="workspace-loading" aria-busy="true">Preparo l’esploratore…</section>}><ThemeWorkspace data={data} themeLabel="consumo di suolo" /></Suspense>
    </main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="soil" /><section className="page-intro"><h1>Consumo di suolo</h1><p role="alert">Dati CDN non configurati o release non ancora pubblicata.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
import { Suspense } from "react";
