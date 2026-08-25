import { MapSidebar } from "./map-sidebar";

type DomainWorkspaceProps = {
  eyebrow: string;
  title: string;
  description: string;
  coverage: string;
  status: string;
  metrics: string[];
  reading: string;
  sourceNote: string;
  methodology: string;
  domainClass?: string;
};

export function DomainWorkspace({
  eyebrow, title, description, coverage, status, metrics, reading, sourceNote, methodology, domainClass = "",
}: DomainWorkspaceProps) {
  return <section className={`domain-site-layout ${domainClass}`} aria-label={`Esplorazione ${title}`}>
    <MapSidebar title={title}>
      <a className="sidebar-link sidebar-atlas-link" href="#atlante">Vai alla mappa ↓</a>
      <section className="sidebar-section">
        <h3>Stato della release</h3>
        <p className="sidebar-context"><strong>{status}</strong>{sourceNote}</p>
      </section>
      <section className="sidebar-section">
        <h3>Prime metriche</h3>
        <ul className="domain-metric-list">{metrics.map((metric) => <li key={metric}>{metric}</li>)}</ul>
      </section>
      <section className="sidebar-section">
        <h3>Copertura</h3>
        <p className="sidebar-context"><strong>{coverage}</strong>Solo granularità e periodi dichiarati dalla fonte.</p>
      </section>
      <a className="sidebar-link" href="#metodo">Fonte e limiti →</a>
    </MapSidebar>
    <div className="domain-site-content">
      <section className="domain-hero">
        <div className="domain-hero-title"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>
        <div className="domain-hero-copy"><p>{description}</p><a className="primary-link" href="#atlante">Vedi struttura atlante <span aria-hidden="true">→</span></a></div>
        <section className="domain-hero-context" aria-label="Copertura del dominio"><div><p className="eyebrow">Copertura iniziale</p><strong>{coverage}</strong></div><p>{reading}</p></section>
      </section>
      <section id="atlante" className="domain-workspace" tabIndex={-1} aria-labelledby="domain-atlas-title">
        <div className="domain-state-stage" role="status" aria-live="polite">
          <p className="eyebrow">Release dati in preparazione</p>
          <h2 id="domain-atlas-title">Mappa pronta. Valori ancora no.</h2>
          <p>Qui compariranno legenda, controlli e dati ufficiali appena la release supera validazione e provenienza.</p>
        </div>
        <section id="metodo" className="domain-method"><p className="eyebrow">Come leggere</p><p>{methodology}</p></section>
      </section>
    </div>
  </section>;
}
