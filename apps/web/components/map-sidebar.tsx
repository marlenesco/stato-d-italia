"use client";

import type { ReactNode } from "react";

type MenuItem = { id: string; label: string; meta?: string };

export function MapSidebar({ title, children }: { title: string; children: ReactNode }) {
  return <aside className="map-sidebar" aria-label={`${title}: controlli e contesto`}><p className="eyebrow">Esplora dati</p><h2>{title}</h2>{children}</aside>;
}

export function ExposedMenu({ label, items, value, onChange }: { label: string; items: MenuItem[]; value: string; onChange: (id: string) => void }) {
  return <section className="sidebar-section"><h3>{label}</h3><div className="exposed-menu" role="group" aria-label={label}>{items.map((item) => <button type="button" key={item.id} onClick={() => onChange(item.id)} aria-pressed={item.id === value}><span>{item.label}</span>{item.meta && <small>{item.meta}</small>}</button>)}</div></section>;
}
