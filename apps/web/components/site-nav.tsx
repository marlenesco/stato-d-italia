"use client";

import Link from "next/link";
import { useState } from "react";

type Section = "home" | "soil" | "water" | "forests" | "emissions" | "hydrogeological-risk" | "territory";

const items: Array<{ id: Exclude<Section, "territory">; href: string; label: string }> = [
  { id: "home", href: "/", label: "Panoramica" },
  { id: "soil", href: "/suolo", label: "Suolo" },
  { id: "water", href: "/acqua", label: "Acqua" },
  { id: "forests", href: "/foreste", label: "Foreste" },
  { id: "emissions", href: "/emissioni", label: "Emissioni" },
  { id: "hydrogeological-risk", href: "/dissesto", label: "Dissesto" },
];

export function SiteNav({ section }: { section?: Section }) {
  const [open, setOpen] = useState(false);
  return <header className="masthead">
    <Link className="site-brand" href="/">STATO D&apos;ITALIA</Link>
    <button className="site-nav-toggle" type="button" aria-expanded={open} aria-controls="site-sections" onClick={() => setOpen((current) => !current)}>{open ? "Chiudi" : "Sezioni"}<span aria-hidden="true">{open ? "×" : "+"}</span></button>
    <nav id="site-sections" className="site-nav" data-open={open ? "true" : "false"} aria-label="Sezioni">
      {items.map((item, index) => <Link key={item.id} href={item.href} onClick={() => setOpen(false)} aria-current={section === item.id ? "page" : undefined}><span>{String(index + 1).padStart(2, "0")}</span>{item.label}</Link>)}
    </nav>
  </header>;
}
