"use client";

import type { ReactNode } from "react";

export type MenuItem = { id: string; label: string; meta?: string };
export type MenuGroup = { id: string; label: string; meta?: string; items: MenuItem[] };

export function MapSidebar({ title, children }: { title: string; children: ReactNode }) {
  return <aside className="map-sidebar" aria-label={`${title}: controlli e contesto`}><p className="eyebrow">Esplora dati</p><h2>{title}</h2>{children}</aside>;
}

export function ExposedMenu({ label, items, groups, value, onChange }: { label: string; items: MenuItem[]; groups?: MenuGroup[]; value: string; onChange: (id: string) => void }) {
  const renderedGroups = groups?.filter((group) => group.items.length) ?? [{ id: "all", label: "", items }];
  return <section className="sidebar-section"><h3>{label}</h3><div className="exposed-menu">{renderedGroups.map((group) => <section className="exposed-menu-group" key={group.id} aria-label={group.label || label}>{group.label && <header><strong>{group.label}</strong>{group.meta && <small>{group.meta}</small>}</header>}<div role="group" aria-label={group.label || label}>{group.items.map((item) => <button type="button" key={item.id} onClick={() => onChange(item.id)} aria-pressed={item.id === value}><span>{item.label}</span>{item.meta && <small>{item.meta}</small>}</button>)}</div></section>)}</div></section>;
}
