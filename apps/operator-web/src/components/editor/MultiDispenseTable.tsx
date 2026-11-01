import { useState } from "react";
import * as theme from "../../theme";
import { multiDispenseErrors } from "../../utils/multiDispense";

interface Props {
  stepIndex: number;
  args: Record<string, unknown>;
  positions: string[];
  onChange: (destinations: unknown[], volumes: unknown[]) => void;
}

export default function MultiDispenseTable({ stepIndex, args, positions, onChange }: Props) {
  const errors = multiDispenseErrors(args);
  const listId = `multi-dispense-${stepIndex}-positions`;
  const errorId = `multi-dispense-${stepIndex}-errors`;
  const editable = Array.isArray(args.destinations) && Array.isArray(args.volumes);
  const destinations = Array.isArray(args.destinations) ? args.destinations : [];
  const volumes = Array.isArray(args.volumes) ? args.volumes : [];
  const rows = Array.from({ length: Math.max(destinations.length, volumes.length) }, (_, i) => ({
    destination: destinations[i] ?? "",
    volume: volumes[i] ?? "",
  }));
  const commit = (next: typeof rows) => onChange(next.map(r => r.destination), next.map(r => r.volume));

  return (
    <div style={{ marginTop: 12 }}>
      {editable && <>
        <datalist id={listId}>
          {positions.map(position => <option key={position} value={position} />)}
        </datalist>
        <table aria-label={`Step ${stepIndex + 1} dispense destinations`} style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
          <thead>
            <tr>
              <th scope="col" style={headingStyle}>Destination</th>
              <th scope="col" style={{ ...headingStyle, width: "30%" }}>Volume (µL)</th>
              <th scope="col" aria-label="Row actions" style={{ width: 64 }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td style={cellStyle}>
                  <input
                    aria-label={`Step ${stepIndex + 1} destination ${i + 1}`}
                    aria-invalid={typeof row.destination !== "string" || !row.destination.trim()}
                    aria-describedby={errors.length ? errorId : undefined}
                    list={listId}
                    value={String(row.destination)}
                    placeholder="plate.B1"
                    onChange={e => commit(rows.map((r, j) => j === i ? { ...r, destination: e.target.value } : r))}
                    style={inputStyle}
                  />
                </td>
                <td style={cellStyle}>
                  <VolumeInput
                    label={`Step ${stepIndex + 1} volume ${i + 1} (µL)`}
                    errorId={errors.length ? errorId : undefined}
                    value={row.volume}
                    onChange={volume => commit(rows.map((r, j) => j === i ? { ...r, volume } : r))}
                  />
                </td>
                <td style={{ ...cellStyle, textAlign: "right" }}>
                  <button type="button" aria-label={`Remove destination ${i + 1} from step ${stepIndex + 1}`}
                    onClick={() => commit(rows.filter((_, j) => j !== i))} style={theme.btn.danger}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" aria-label="Add destination" onClick={() => commit([...rows, { destination: "", volume: "" }])}
          style={{ ...theme.btn.secondary, marginTop: 8 }}>+ Add destination</button>
      </>}
      {errors.length > 0 && <div id={errorId} role="alert" style={{ ...theme.notice.error, marginTop: 8 }}>
        {errors.map(error => <div key={error}>{error}</div>)}
      </div>}
    </div>
  );
}

function VolumeInput({ value, label, errorId, onChange }: {
  value: unknown; label: string; errorId?: string; onChange: (value: unknown) => void;
}) {
  const [draft, setDraft] = useState({ value, raw: String(value) });
  if (!Object.is(value, draft.value)) setDraft({ value, raw: String(value) });
  return <input
    aria-label={label}
    aria-invalid={typeof value !== "number" || !Number.isFinite(value) || value <= 0}
    aria-describedby={errorId}
    inputMode="decimal"
    value={draft.raw}
    placeholder="µL"
    onChange={e => {
      const raw = e.target.value;
      const parsed = raw.trim() && /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(raw.trim())
        ? Number(raw) : NaN;
      const next = Number.isFinite(parsed) ? parsed : raw;
      setDraft({ raw, value: next });
      onChange(next);
    }}
    style={inputStyle}
  />;
}

const inputStyle: React.CSSProperties = { ...theme.input, width: "100%", minWidth: 0, boxSizing: "border-box" };
const cellStyle: React.CSSProperties = { padding: "4px 6px 4px 0", verticalAlign: "top" };
const headingStyle: React.CSSProperties = { ...theme.fieldLabel, textAlign: "left", padding: "0 6px 4px 0" };
