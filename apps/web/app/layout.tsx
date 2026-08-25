import type { Metadata } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";
import "./mobile-overrides.css";

export const metadata: Metadata = {
  title: "Stato d'Italia",
  description: "Dati ambientali e territoriali ufficiali, confrontabili nel tempo.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="it"><body>{children}</body></html>;
}
