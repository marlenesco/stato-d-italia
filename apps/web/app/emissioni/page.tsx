import { EmissionsWorkspace } from "../../components/emissions-workspace";
import { SiteNav } from "../../components/site-nav";
import { loadEmissionsData } from "../../lib/data";

export const revalidate = 60;

export default async function EmissionsPage() {
  try {
    const data = await loadEmissionsData();
    return <main className="shell domain-shell"><SiteNav section="emissions" /><EmissionsWorkspace data={data} /></main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="emissions" /><section className="page-intro"><h1>Emissioni</h1><p role="alert">Dati emissioni non ancora pubblicati nella release locale.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
