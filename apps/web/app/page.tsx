import { HomeOverview } from "../components/home-overview";
import { SiteNav } from "../components/site-nav";
import { loadHomeOverview } from "../lib/data";

export const revalidate = 60;

export default async function Home() {
  try {
    const overview = await loadHomeOverview();
    return <main className="shell home-shell"><SiteNav section="home" /><HomeOverview overview={overview} /></main>;
  } catch {
    return <main className="shell"><SiteNav section="home" /><section className="page-intro"><p className="eyebrow">Osservatorio territoriale</p><h1>Italia, dati in arrivo.</h1><p role="alert">Panoramica non disponibile: attendi una release dati completa.</p></section></main>;
  }
}
