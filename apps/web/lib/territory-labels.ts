const regionNames: Record<string, string> = {
  "01": "Piemonte", "02": "Valle d'Aosta", "03": "Lombardia", "04": "Trentino-Alto Adige", "05": "Veneto",
  "06": "Friuli-Venezia Giulia", "07": "Liguria", "08": "Emilia-Romagna", "09": "Toscana", "10": "Umbria",
  "11": "Marche", "12": "Lazio", "13": "Abruzzo", "14": "Molise", "15": "Campania", "16": "Puglia",
  "17": "Basilicata", "18": "Calabria", "19": "Sicilia", "20": "Sardegna",
};

const levelNames: Record<string, string> = { municipality: "Comune", province: "Provincia", region: "Regione", country: "Italia" };

/** UI fallback only. Official names from profile/ranking artifacts always win. */
export function territoryLabel(territoryId: string, officialName?: string) {
  if (officialName) return officialName;
  const [country, level, code] = territoryId.split(":");
  if (country !== "it" || !level || !code) return "Territorio non identificato";
  if (level === "country") return "Italia";
  if (level === "region") return regionNames[code] ?? `Regione ISTAT ${code}`;
  return `${levelNames[level] ?? "Territorio"} ISTAT ${code}`;
}

export function territoryIstatCode(territoryId: string, officialCode?: string) {
  return officialCode ?? territoryId.split(":")[2] ?? "—";
}
