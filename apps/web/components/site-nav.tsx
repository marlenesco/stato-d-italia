import Link from "next/link";

type Section = "home" | "soil" | "water" | "territory";

const items: Array<{ id: Exclude<Section, "territory">; href: string; label: string }> = [
  { id: "home", href: "/", label: "Panoramica" },
  { id: "soil", href: "/suolo", label: "Suolo" },
  { id: "water", href: "/acqua", label: "Acqua" },
];

export function SiteNav({ section }: { section?: Section }) {
  return <header className="masthead">
    <Link className="site-brand" href="/">STATO D&apos;ITALIA</Link>
    <nav className="site-nav" aria-label="Sezioni">
      {items.map((item) => <Link key={item.id} href={item.href} aria-current={section === item.id ? "page" : undefined}>{item.label}</Link>)}
    </nav>
  </header>;
}
