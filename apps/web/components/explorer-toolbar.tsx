import type { MenuGroup, MenuItem } from "./map-sidebar";

type Level = { id: string; label: string };

export function ExplorerToolbar({
  label,
  items,
  groups,
  value,
  onChange,
  levels = [],
  level,
  onLevelChange,
  context,
}: {
  label: string;
  items: MenuItem[];
  groups?: MenuGroup[];
  value: string;
  onChange: (id: string) => void;
  levels?: Level[];
  level?: string;
  onLevelChange?: (id: string) => void;
  context?: string;
}) {
  const groupedIds = new Set(groups?.flatMap((group) => group.items.map((item) => item.id)) ?? []);
  const ungrouped = items.filter((item) => !groupedIds.has(item.id));

  return <section className="explorer-toolbar" aria-label="Filtri della mappa">
    <label className="explorer-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {groups?.map((group) => <optgroup key={group.id} label={group.label}>{group.items.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</optgroup>)}
        {ungrouped.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
    </label>
    {levels.length > 0 && level && onLevelChange && <fieldset className="explorer-levels">
      <legend>Livello territoriale</legend>
      <div>{levels.map((item) => <button type="button" key={item.id} onClick={() => onLevelChange(item.id)} aria-pressed={item.id === level}>{item.label}</button>)}</div>
    </fieldset>}
    {context && <p className="explorer-context">{context}</p>}
  </section>;
}
