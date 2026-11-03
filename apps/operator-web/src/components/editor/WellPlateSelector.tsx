import { Fragment } from "react";

function layout(wells: string[]) {
  const matches = wells.map(w => /^([A-Za-z]+)(\d+)$/.exec(w));
  if (matches.some(m => !m)) return null;
  return {
    rows: [...new Set(matches.map(m => m![1]))].sort((a,b) => a.length-b.length || a.localeCompare(b)),
    columns: [...new Set(matches.map(m => m![2]))].sort((a,b) => Number(a)-Number(b)),
  };
}
export function PlatePreview({ wells }: { wells: string[] }) {
  const grid = layout(wells);
  const cols = grid?.columns.length || 6;
  const rows = grid?.rows.length || Math.ceil(wells.length / cols);
  return <svg className="repeat-mini-plate" viewBox={`0 0 ${cols*8+16} ${rows*8+16}`} aria-hidden="true">
    <rect x="1" y="1" width={cols*8+14} height={rows*8+14} rx="5" fill="currentColor" fillOpacity=".06" stroke="currentColor" strokeOpacity=".35" />
    {wells.map((well,i) => {
      const m = /^([A-Za-z]+)(\d+)$/.exec(well);
      const x = grid && m ? grid.columns.indexOf(m[2]) : i % cols;
      const y = grid && m ? grid.rows.indexOf(m[1]) : Math.floor(i / cols);
      return <circle key={well} cx={12+x*8} cy={12+y*8} r="2" fill="currentColor" fillOpacity=".5" />;
    })}
  </svg>;
}
export function WellPlateSelector({ wells, selected, template, onChange }: {
  wells: string[]; selected: string[]; template: string; onChange: (wells: string[]) => void;
}) {
  const grid = layout(wells);
  const chosen = new Set(selected);
  const toggle = (group: string[]) => {
    const remove = group.every(w => chosen.has(w));
    const members = new Set(group);
    onChange(wells.filter(w => members.has(w) ? !remove : chosen.has(w)));
  };
  const wellButton = (well: string) => <button key={well} type="button"
    className={`repeat-well${well === template ? " repeat-well-template" : ""}`}
    aria-label={`Repeat target ${well}`} aria-pressed={chosen.has(well)}
    title={`${well}${well === template ? " · Template" : ""}`} onClick={() => toggle([well])}>{well}</button>;
  return <div className="repeat-plate-selector">
    <div className="repeat-plate-toolbar"><span>Target wells <strong>{wells.filter(w => chosen.has(w)).length}/{wells.length}</strong></span>
      <div><button type="button" onClick={() => onChange(wells)}>Select all</button><button type="button" onClick={() => onChange([])}>Clear</button></div>
    </div>
    <div className="repeat-plate-scroll">
      {grid ? <div className="repeat-plate" role="group" aria-label="Target well plate"
        style={{ gridTemplateColumns: `28px repeat(${grid.columns.length}, minmax(32px, 1fr))` }}>
        <span aria-hidden="true" />
        {grid.columns.map(col => {
          const group = wells.filter(w => /^([A-Za-z]+)(\d+)$/.exec(w)![2] === col);
          return <button type="button" key={col} className="repeat-axis" aria-label={`Column ${col}`}
            aria-pressed={group.every(w => chosen.has(w))} onClick={() => toggle(group)}>{col}</button>;
        })}
        {grid.rows.map(row => {
          const group = wells.filter(w => /^([A-Za-z]+)(\d+)$/.exec(w)![1] === row);
          return <Fragment key={row}><button type="button" className="repeat-axis" aria-label={`Row ${row}`}
            aria-pressed={group.every(w => chosen.has(w))} onClick={() => toggle(group)}>{row}</button>
            {grid.columns.map(col => wells.includes(`${row}${col}`) ? wellButton(`${row}${col}`) : <span key={col} />)}
          </Fragment>;
        })}
      </div> : <div className="repeat-plate repeat-plate-custom" role="group" aria-label="Target wells">{wells.map(wellButton)}</div>}
    </div>
  </div>;
}
