import { SiteNav } from "../../components/site-nav";
import { Suspense } from "react";
import { ThemeWorkspace } from "../../components/soil-workspace";
import { loadForestData } from "../../lib/data";

export const revalidate = 60;

const labels: Record<string, string> = {
  forest_biomass_infc: "Fitomassa arborea epigea", forest_volume_infc: "Volume del bosco",
  forest_volume_increment_infc: "Incremento annuo di volume", forest_carbon_infc: "Carbonio nella fitomassa arborea epigea",
  forest_cover_hrl: "Copertura forestale HRL", forest_cover_corine: "Copertura forestale CORINE",
  forest_area_ha: "Superficie forestale", forest_share_pct: "Quota di superficie forestale", tree_cover_mean: "Copertura arborea media",
  tree_cover_p25: "25° percentile", tree_cover_p50: "Mediana", tree_cover_p75: "75° percentile",
  broadleaved_area_hrl_ha: "Latifoglie", coniferous_area_hrl_ha: "Conifere", mixed_forest_area_hrl_ha: "Bosco misto",
  broadleaved_area_dlt_ha: "Copertura arborea di latifoglie DLT", coniferous_area_dlt_ha: "Copertura arborea di conifere DLT",
  broadleaved_area_corine_ha: "Superficie di latifoglie CORINE", coniferous_area_corine_ha: "Superficie di conifere CORINE", mixed_forest_area_corine_ha: "Superficie forestale mista CORINE",
  tree_cover_gain_ha: "Nuova copertura arborea", tree_cover_loss_ha: "Perdita di copertura arborea",
};

const derivedStatus = {
  sourceNote: "Elaborazione Stato d’Italia su dati Copernicus; non valore territoriale pubblicato direttamente dalla fonte.",
  mapStatusNote: "Mappa: elaborazioni Stato d’Italia su Copernicus. Non sono valori territoriali pubblicati direttamente dalla fonte.",
  seriesStatusNote: "Elaborazione Stato d’Italia; nessuna interpolazione.",
} as const;

const officialInfcStatus = {
  sourceNote: "Statistica ufficiale INFC pubblicata; non elaborazione zonale Copernicus.",
  mapStatusNote: "Mappa: statistiche ufficiali INFC. Solo territori e anni realmente pubblicati.",
  seriesStatusNote: "Statistica ufficiale INFC; nessuna interpolazione.",
} as const;

const guides = {
  forest_biomass_infc: { family: "Patrimonio forestale", source: "INFC · statistica ufficiale pubblicata", reading: "È il peso secco della parte arborea sopra il terreno. Descrive quanta materia legnosa è presente; non misura né ettari di bosco né un assorbimento annuo di carbonio.", ...officialInfcStatus },
  forest_volume_infc: { family: "Patrimonio forestale", source: "INFC · statistica ufficiale pubblicata", reading: "È il volume stimato degli alberi secondo le definizioni INFC. Aiuta a descrivere quanto legno è presente, non l’estensione del bosco.", ...officialInfcStatus },
  forest_volume_increment_infc: { family: "Patrimonio forestale", source: "INFC · statistica ufficiale pubblicata", reading: "È il volume che il patrimonio forestale aggiunge mediamente ogni anno. Non indica nuova superficie boscata.", ...officialInfcStatus },
  forest_carbon_infc: { family: "Carbonio", source: "INFC · statistica ufficiale pubblicata", reading: "È il carbonio contenuto nella fitomassa arborea epigea. È uno stock nel patrimonio forestale, non un flusso annuo di emissioni o assorbimenti.", ...officialInfcStatus },
  forest_cover_hrl: { family: "Copertura forestale", source: "Copernicus HRL · elaborazione Stato d’Italia", reading: "Superficie classificata dal prodotto HRL. Confrontala solo con stesso prodotto, anno e livello; non è serie continua con CORINE.", ...derivedStatus },
  forest_cover_corine: { family: "Storico lungo", source: "CORINE Land Cover · elaborazione Stato d’Italia", reading: "Superficie delle classi forestali CORINE. Leggila come storico separato: CORINE e HRL hanno metodi e risoluzioni differenti.", ...derivedStatus },
  tree_cover_mean: { family: "Copertura arborea", source: "Copernicus HRL · elaborazione Stato d’Italia", reading: "Media percentuale di suolo coperta dalle chiome nel territorio. Non equivale a superficie forestale: alberi urbani e filari possono contribuire.", ...derivedStatus },
  tree_cover_p25: { family: "Distribuzione della copertura", source: "Copernicus HRL · elaborazione Stato d’Italia", reading: "Sotto questo valore ricade un quarto dei pixel. Leggilo insieme a mediana e 75° percentile, non come quota di foresta.", ...derivedStatus },
  tree_cover_p50: { family: "Distribuzione della copertura", source: "Copernicus HRL · elaborazione Stato d’Italia", reading: "La mediana separa a metà i pixel meno e più coperti da chiome. È utile insieme alla fascia 25°–75° percentile.", ...derivedStatus },
  tree_cover_p75: { family: "Distribuzione della copertura", source: "Copernicus HRL · elaborazione Stato d’Italia", reading: "Sopra questo valore ricade il quarto dei pixel più coperto da chiome. Leggilo insieme a media e mediana.", ...derivedStatus },
  forest_area_ha: { family: "Superficie forestale", source: "Copernicus HRL Forest Type · elaborazione Stato d’Italia", reading: "Ettari classificati come foresta HRL. Diversa da tree cover: classificazione applica regole proprie del prodotto.", ...derivedStatus },
  forest_share_pct: { family: "Superficie forestale", source: "Copernicus HRL Forest Type · elaborazione Stato d’Italia", reading: "Quota del territorio classificata come foresta HRL. Utile per confronti solo nello stesso anno e livello territoriale.", ...derivedStatus },
  broadleaved_area_hrl_ha: { family: "Composizione", source: "Copernicus HRL Forest Type · elaborazione Stato d’Italia", reading: "Ettari classificati come foresta di latifoglie. Confronta con conifere e misto, non con DLT o CORINE.", ...derivedStatus },
  coniferous_area_hrl_ha: { family: "Composizione", source: "Copernicus HRL Forest Type · elaborazione Stato d’Italia", reading: "Ettari classificati come foresta di conifere.", ...derivedStatus },
  mixed_forest_area_hrl_ha: { family: "Composizione", source: "Copernicus HRL Forest Type · elaborazione Stato d’Italia", reading: "Ettari classificati come foresta mista dal prodotto HRL 100 m.", ...derivedStatus },
  broadleaved_area_dlt_ha: { family: "Composizione", source: "Copernicus HRL Dominant Leaf Type · elaborazione Stato d’Italia", reading: "Copertura arborea attribuita alle latifoglie dal prodotto DLT. Non è identica alla classe forestale HRL Forest Type.", ...derivedStatus },
  coniferous_area_dlt_ha: { family: "Composizione", source: "Copernicus HRL Dominant Leaf Type · elaborazione Stato d’Italia", reading: "Copertura arborea attribuita alle conifere dal prodotto DLT. Non sommarla a Forest Type o CORINE.", ...derivedStatus },
  broadleaved_area_corine_ha: { family: "Storico lungo", source: "CORINE Land Cover · elaborazione Stato d’Italia", reading: "Superficie CORINE della classe 311: boschi di latifoglie. Serie separata da HRL.", ...derivedStatus },
  coniferous_area_corine_ha: { family: "Storico lungo", source: "CORINE Land Cover · elaborazione Stato d’Italia", reading: "Superficie CORINE della classe 312: boschi di conifere. Serie separata da HRL.", ...derivedStatus },
  mixed_forest_area_corine_ha: { family: "Storico lungo", source: "CORINE Land Cover · elaborazione Stato d’Italia", reading: "Superficie CORINE della classe 313: boschi misti. Serie separata da HRL.", ...derivedStatus },
  tree_cover_gain_ha: { family: "Cambiamento", source: "Copernicus HRL Tree Cover Presence Change · elaborazione Stato d’Italia", reading: "Nuova copertura arborea nel periodo pubblicato. Non dimostra da sola cambio permanente d’uso del suolo.", ...derivedStatus },
  tree_cover_loss_ha: { family: "Cambiamento", source: "Copernicus HRL Tree Cover Presence Change · elaborazione Stato d’Italia", reading: "Perdita di copertura arborea nel periodo pubblicato. Non chiamarla deforestazione: prodotto non prova cambio permanente d’uso.", ...derivedStatus },
} as const;

export default async function ForestsPage() {
  try {
    const data = await loadForestData();
    return <main className="shell soil-shell"><SiteNav section="forests" /><Suspense fallback={<section className="workspace-loading" aria-busy="true">Preparo l’atlante forestale…</section>}><ThemeWorkspace data={data} themeLabel="foreste" config={{ title: "Foreste", eyebrow: "Copernicus HRL · INFC", description: "Scegli misura, anno e territorio. Copernicus mostra elaborazioni zonali Stato d’Italia; INFC resta statistica ufficiale complementare.", metricLabels: labels, metricGuides: guides, defaultMetric: "tree_cover_mean", hiddenMetricIds: ["forest_cover_hrl"], metricAliases: { forest_cover_hrl: "forest_area_ha" }, metricGroups: [{ id: "extent", label: "Estensione del bosco", meta: "Copernicus HRL Forest Type · 2018, 2021", metricIds: ["forest_area_ha", "forest_share_pct"] }, { id: "composition", label: "Composizione", meta: "Copernicus HRL Forest Type · 2018, 2021", metricIds: ["broadleaved_area_hrl_ha", "coniferous_area_hrl_ha", "mixed_forest_area_hrl_ha"] }, { id: "cover", label: "Copertura delle chiome", meta: "Tree Cover Density · 2018, 2021, 2023", metricIds: ["tree_cover_mean"] }, { id: "distribution", label: "Distribuzione della copertura", meta: "Tree Cover Density · 2018, 2021, 2023", metricIds: ["tree_cover_p25", "tree_cover_p50", "tree_cover_p75"] }, { id: "change", label: "Cambiamento", meta: "Tree Cover Change · 2018–2021", metricIds: ["tree_cover_gain_ha", "tree_cover_loss_ha"] }, { id: "assets", label: "Patrimonio forestale", meta: "INFC · solo Regioni · 2015", metricIds: ["forest_biomass_infc", "forest_volume_infc", "forest_volume_increment_infc"] }, { id: "carbon", label: "Carbonio", meta: "INFC · solo Regioni · 2015", metricIds: ["forest_carbon_infc"] }], forestCompanions: [{ id: "composition", metricIds: ["broadleaved_area_hrl_ha", "coniferous_area_hrl_ha", "mixed_forest_area_hrl_ha"], title: "Composizione forestale", description: "Le tre classi HRL possono essere lette insieme: mostrano ettari classificati come latifoglie, conifere o bosco misto." }, { id: "distribution", metricIds: ["tree_cover_mean", "tree_cover_p25", "tree_cover_p50", "tree_cover_p75"], title: "Distribuzione della copertura arborea", description: "Media e percentili descrivono la copertura delle chiome all’interno dello stesso territorio." }, { id: "change", metricIds: ["tree_cover_gain_ha", "tree_cover_loss_ha"], title: "Cambiamento della copertura arborea", description: "Le due misure si riferiscono allo stesso periodo pubblicato. Non costituiscono una misura di deforestazione." }], dataRoot: "foreste", colorRamp: "forests", sourceNote: derivedStatus.sourceNote, mapStatusNote: derivedStatus.mapStatusNote, seriesStatusNote: derivedStatus.seriesStatusNote, provenanceSummary: "Mappe e serie Copernicus: elaborazioni Stato d’Italia su poligoni ISTAT della data di riferimento. INFC: statistiche ufficiali pubblicate, mantenute separate.", availabilityNote: "Solo anni e livelli realmente presenti nella release.", comparisonNote: "Confronto nel solo campione Copernicus: Lazio, Lombardia, Toscana e Sicilia. Non è una classifica nazionale.", domainClass: "domain-forests" }} /></Suspense></main>;
  } catch (error) {
    return <main className="shell"><SiteNav section="forests" /><section className="page-intro"><h1>Foreste</h1><p role="alert">Dati foreste non ancora pubblicati nella release locale.</p><code>{error instanceof Error ? error.message : "Errore dati"}</code></section></main>;
  }
}
