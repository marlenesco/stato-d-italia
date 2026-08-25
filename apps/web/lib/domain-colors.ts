export type DomainColorRamp = {
  low: string;
  mid: string;
  high: string;
  surface: string;
  outline: string;
};

/** Topic identity only: legend and values retain quantitative meaning. */
export const domainColorRamps = {
  soil: { low: "#f2e7be", mid: "#d98c4b", high: "#8e2f25", surface: "#f1f2ec", outline: "#fffdf7" },
  water: { low: "#e9f0e7", mid: "#78b5b4", high: "#075c70", surface: "#eef3ee", outline: "#fffdf7" },
  dissesto: { low: "#ede9fe", mid: "#a78bfa", high: "#5b21b6", surface: "#f4f1ff", outline: "#fffdf7" },
  emissions: { low: "#eeebf2", mid: "#9588ad", high: "#4c3d68", surface: "#f2f0f4", outline: "#fffdf7" },
  forests: { low: "#e5eee3", mid: "#6e9b70", high: "#285b42", surface: "#edf3eb", outline: "#fffdf7" },
  fires: { low: "#f7ead9", mid: "#d47a42", high: "#9b3d25", surface: "#f8efe6", outline: "#fffdf7" },
  air: { low: "#e8eef5", mid: "#7198bd", high: "#245b84", surface: "#eff3f7", outline: "#fffdf7" },
  climate: { low: "#f0e9f3", mid: "#9a7caf", high: "#604170", surface: "#f4eff5", outline: "#fffdf7" },
  energy: { low: "#f7efd8", mid: "#c99c3d", high: "#876014", surface: "#f8f3e6", outline: "#fffdf7" },
  biodiversity: { low: "#eef0df", mid: "#9da35a", high: "#59662d", surface: "#f3f4e9", outline: "#fffdf7" },
} as const;

export type DomainColorName = keyof typeof domainColorRamps;
