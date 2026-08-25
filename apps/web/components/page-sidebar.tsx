import type { ReactNode } from "react";

export function PageSidebar({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return <aside className="page-sidebar" aria-label={`${title}: contesto e navigazione`}><p className="eyebrow">{eyebrow}</p><h2>{title}</h2>{children}</aside>;
}
