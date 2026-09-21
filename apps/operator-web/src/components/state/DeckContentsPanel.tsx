import { useMemo, useState } from "react";
import * as theme from "../../theme";
import { ApiError } from "../../api/client";
import {
  useActiveFluidState,
  useApplyManualEdits,
  useCreateFluidState,
  useFluidState,
  useFluidStates,
  useSelectActiveFluidState,
} from "../../hooks/useFluidState";
import type { ContainerView } from "../../types";
import type { ManualEditAction, ManualEditMode } from "../../types";

interface Props {
  deckFile?: string | null;
  isRunActive?: boolean;
}

function volumeLabel(value: number): string {
  if (!Number.isFinite(value)) return "Unknown";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} mL` : `${value.toFixed(1)} µL`;
}

function compositionLabel(composition: Record<string, number>): string {
  const entries = Object.entries(composition ?? {});
  return entries.length ? entries.map(([name, value]) => `${name} ${volumeLabel(value)}`).join(", ") : "No composition recorded";
}

export default function DeckContentsPanel({ deckFile, isRunActive = false }: Props) {
  const states = useFluidStates();
  const active = useActiveFluidState();
  const activeId = active.data?.fluid_state_id ?? null;
  const [viewId, setViewId] = useState<number | null>(null);
  const selectedId = viewId ?? activeId;
  const detail = useFluidState(selectedId);
  const selectActive = useSelectActiveFluidState();
  const createState = useCreateFluidState();
  const applyEdits = useApplyManualEdits(selectedId);
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<ContainerView | null>(null);
  const [volume, setVolume] = useState("");
  const [composition, setComposition] = useState("");
  const [mode, setMode] = useState<ManualEditMode>("set");
  const [destination, setDestination] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("");

  const rows = detail.data?.containers ?? [];
  const allSelected = rows.length > 0 && rows.every((row) => selectedRows.has(`${row.labware_key}:${row.location_id}`));
  const isHistorical = selectedId !== null && selectedId !== activeId;
  const activeSummary = states.data?.find((state) => state.id === activeId);

  const operations = useMemo(() => {
    const count = detail.data?.pending_operation_count ?? 0;
    return count ? `${count} pending journal operation${count === 1 ? "" : "s"}` : "Journal is clear";
  }, [detail.data]);

  const toggleAll = () => {
    setSelectedRows(allSelected ? new Set() : new Set(rows.map((row) => `${row.labware_key}:${row.location_id}`)));
  };

  const openEdit = (row: ContainerView) => {
    setEditing(row);
    setVolume(String(row.current_volume_ul));
    setComposition(Object.entries(row.composition ?? {}).map(([name, value]) => `${name}=${value}`).join(", "));
    setMode("set");
    setDestination("");
    setNotice(null);
  };

  const parseComposition = (): Record<string, number> => {
    const result: Record<string, number> = {};
    for (const entry of composition.split(",")) {
      const [name, rawValue] = entry.split("=").map((part) => part.trim());
      if (!name && !rawValue) continue;
      const parsed = Number(rawValue);
      if (!name || !Number.isFinite(parsed) || parsed < 0) throw new Error("Use composition like water=900, dye=100.");
      result[name] = parsed;
    }
    return result;
  };

  const saveEdit = async () => {
    if (!editing || selectedId === null) return;
    const parsedVolume = Number(volume);
    if (!Number.isFinite(parsedVolume) || parsedVolume < 0) {
      setNotice("Enter a volume of 0 or greater.");
      return;
    }
    try {
      const parsedComposition = parseComposition();
      const targets = selectedRows.size > 1 && mode !== "transfer"
        ? rows.filter((row) => selectedRows.has(`${row.labware_key}:${row.location_id}`))
        : [editing];
      const expectedRevisions: Record<string, number> = {};
      const actions: ManualEditAction[] = targets.map((target) => {
        const identity = `${target.labware_key}.${target.location_id}`;
        expectedRevisions[identity] = target.version;
        return { mode, labware_key: target.labware_key, location_id: target.location_id, volume_ul: mode === "empty" ? 0 : parsedVolume, composition: mode === "set" ? parsedComposition : undefined };
      });
      const [destinationKey, destinationLocation] = destination.split(".", 2);
      if (mode === "transfer" && !destinationKey) throw new Error("Enter a destination like reservoir.A1.");
      if (mode === "transfer") {
        actions[0].destination_labware_key = destinationKey;
        actions[0].destination_location_id = destinationLocation ?? "";
      }
      await applyEdits.mutateAsync({ expected_revisions: expectedRevisions, actions, note: "Record manual change" });
      setEditing(null);
      setNotice("Recorded manual change. No robot command was issued.");
    } catch (error) {
      setNotice(error instanceof ApiError && error.status === 409
        ? "This row changed elsewhere. Refresh and review it before saving again."
      : error instanceof Error ? error.message : String(error));
    }
  };

  const create = async () => {
    if (!deckFile) {
      setNotice("Load a deck configuration before creating a physical setup.");
      return;
    }
    try {
      const summary = await createState.mutateAsync({ deck_file: deckFile, label: newLabel.trim() || null });
      await selectActive.mutateAsync({ fluidStateId: summary.id });
      setViewId(null);
      setNewLabel("");
      setNotice("Fresh setup created and activated. Record the observed contents before running.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <section style={panelStyle} aria-label="Deck contents">
      <div style={headerStyle}>
        <div>
          <h3 style={theme.panelTitle}>Deck contents</h3>
          <div style={subtitleStyle}>One explicit physical setup for successive runs</div>
        </div>
        <button type="button" style={theme.btn.secondary} onClick={() => { void states.refetch(); void active.refetch(); }}>
          Refresh
        </button>
      </div>

      <div style={activeBannerStyle}>
        <div>
          <strong>{activeSummary ? `Active setup #${activeSummary.id}` : "No active physical setup"}</strong>
          <div style={metaStyle}>{activeSummary?.label || activeSummary?.deck_path || "Create or activate a setup before a tracked run."}</div>
          {active.data && <div style={metaStyle}>Updated {new Date(active.data.updated_at).toLocaleString()} · revision {active.data.revision}</div>}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
          <input aria-label="New setup label" value={newLabel} onChange={(event) => setNewLabel(event.target.value)} placeholder="Fresh setup name" style={theme.input} disabled={isRunActive} />
          <button type="button" style={theme.btn.primary} disabled={isRunActive || createState.isPending} onClick={() => void create()}>
            {createState.isPending ? "Creating…" : "Prepare fresh setup"}
          </button>
        </div>
      </div>

      {isRunActive && <div style={theme.notice.warning}>A run owns the active setup. Manual changes are disabled until it finishes.</div>}
      {notice && <div role="status" style={theme.notice.info}>{notice}</div>}

      <div style={historyBarStyle}>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={theme.fieldLabel}>View history</span>
          <select aria-label="Contents history" value={viewId ?? "active"} onChange={(event) => setViewId(event.target.value === "active" ? null : Number(event.target.value))} style={selectStyle}>
            <option value="active">Active setup{activeId ? ` #${activeId}` : ""}</option>
            {(states.data ?? []).filter((state) => state.id !== activeId).map((state) => <option key={state.id} value={state.id}>Historical #{state.id}{state.label ? ` — ${state.label}` : ""}</option>)}
          </select>
        </label>
        {isHistorical && <span style={historyPillStyle}>Historical view · viewing does not activate this setup</span>}
        <span style={{ ...metaStyle, marginLeft: "auto" }}>{operations}</span>
      </div>

      {selectedId === null ? <div style={emptyStyle}>No setup selected.</div> : detail.isLoading ? <div style={emptyStyle}>Loading contents…</div> : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <button type="button" style={theme.btn.secondary} disabled={isHistorical || isRunActive || selectActive.isPending || activeId === selectedId} onClick={() => selectActive.mutate({ fluidStateId: selectedId, expectedRevision: active.data?.revision })}>
              {selectActive.isPending ? "Activating…" : activeId === selectedId ? "Active setup" : "Activate this setup"}
            </button>
            <span style={metaStyle}>Select rows for a shared edit. Changes are record-only and auditable.</span>
            {selectedRows.size > 1 && <button type="button" style={theme.btn.ghost} disabled={isHistorical || isRunActive} onClick={() => { const first = rows.find((row) => selectedRows.has(`${row.labware_key}:${row.location_id}`)); if (first) openEdit(first); }}>Edit {selectedRows.size} selected</button>}
          </div>
          <div style={tableFrameStyle}>
            <table style={tableStyle}>
              <thead><tr><th style={thStyle}><input type="checkbox" aria-label="Select all contents" checked={allSelected} onChange={toggleAll} /></th><th style={thStyle}>Location</th><th style={thStyle}>Volume</th><th style={thStyle}>Composition</th><th style={thStyle}>Record</th></tr></thead>
              <tbody>{rows.map((row) => {
                const key = `${row.labware_key}:${row.location_id}`;
                return <tr key={key}>
                  <td style={tdStyle}><input type="checkbox" aria-label={`Select ${row.labware_key} ${row.location_id}`} checked={selectedRows.has(key)} onChange={() => setSelectedRows((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; })} /></td>
                  <td style={tdStyle}><span style={theme.mono}>{row.labware_key}{row.location_id ? `.${row.location_id}` : ""}</span><div style={metaStyle}>{row.role || row.solution || row.labware_type}</div></td>
                  <td style={tdNumericStyle}><strong>{volumeLabel(row.current_volume_ul)}</strong><div style={metaStyle}>working max {volumeLabel(row.working_volume_ul)} · tracked</div></td>
                  <td style={tdStyle}>{compositionLabel(row.composition)}</td>
                  <td style={tdStyle}><button type="button" style={theme.btn.ghost} disabled={isHistorical || isRunActive} onClick={() => openEdit(row)}>Record manual change</button></td>
                </tr>;
              })}</tbody>
            </table>
          </div>
        </>
      )}

      {editing && <div style={dialogStyle} role="dialog" aria-label="Record manual change">
        <div style={theme.sectionLabel}>Record manual change · {editing.labware_key}{editing.location_id ? `.${editing.location_id}` : ""}</div>
        <p style={{ margin: "8px 0", color: theme.color.textSecondary, fontSize: 12 }}>This updates the journaled record only. It never commands the robot.</p>
        <label style={fieldStyle}><span style={theme.fieldLabel}>Change type</span><select value={mode} onChange={(event) => setMode(event.target.value as ManualEditMode)} style={theme.input}><option value="set">Correct to observed</option><option value="add">Add volume</option><option value="remove">Remove volume</option><option value="empty">Record empty</option><option value="transfer">Record manual transfer</option></select></label>
        {mode === "transfer" ? <label style={fieldStyle}><span style={theme.fieldLabel}>Destination</span><input value={destination} onChange={(event) => setDestination(event.target.value)} style={theme.input} placeholder="reservoir.A1" /></label> : <label style={fieldStyle}><span style={theme.fieldLabel}>{mode === "set" ? "Observed volume" : "Volume change"} (µL)</span><input autoFocus value={volume} onChange={(event) => setVolume(event.target.value)} style={theme.input} inputMode="decimal" /></label>}
        {mode === "set" && <label style={fieldStyle}><span style={theme.fieldLabel}>Composition (optional)</span><input value={composition} onChange={(event) => setComposition(event.target.value)} style={theme.input} placeholder="water=900, dye=100" /></label>}
        <div style={{ marginTop: 10, padding: 8, border: `1px solid ${theme.color.border}`, borderRadius: theme.radius.sm, color: theme.color.textSecondary, fontSize: 12 }}>Preview: <strong>{mode}</strong> {mode === "transfer" ? `${volume || "0"} µL → ${destination || "destination"}` : `${volume || "0"} µL`}. This is one atomic journal update.</div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 10 }}><button type="button" style={theme.btn.secondary} onClick={() => setEditing(null)}>Cancel</button><button type="button" style={theme.btn.primary} disabled={applyEdits.isPending} onClick={() => void saveEdit()}>{applyEdits.isPending ? "Saving…" : "Save record"}</button></div>
      </div>}
    </section>
  );
}

const panelStyle = { display: "flex", flexDirection: "column", gap: 12, minHeight: "100%" } as const;
const headerStyle = { display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 } as const;
const subtitleStyle = { color: theme.color.textMuted, fontSize: 12, marginTop: 3 } as const;
const metaStyle = { color: theme.color.textMuted, fontSize: 11, lineHeight: 1.4 } as const;
const activeBannerStyle = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: 12, background: theme.color.accentTint, border: `1px solid ${theme.color.accentTintBorder}`, borderRadius: theme.radius.md, flexWrap: "wrap" } as const;
const historyBarStyle = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "8px 0", borderBottom: `1px solid ${theme.color.border}` } as const;
const historyPillStyle = { color: theme.color.warningText, background: theme.color.warningBg, border: `1px solid ${theme.color.warningBorder}`, borderRadius: 99, padding: "3px 8px", fontSize: 11 } as const;
const selectStyle = { ...theme.input, minWidth: 190 } as const;
const emptyStyle = { padding: 24, textAlign: "center", color: theme.color.textMuted, fontSize: 13 } as const;
const tableFrameStyle = { overflowX: "auto", border: `1px solid ${theme.color.border}`, borderRadius: theme.radius.md } as const;
const tableStyle = { width: "100%", borderCollapse: "collapse", fontSize: 12 } as const;
const thStyle = { textAlign: "left", padding: "8px 10px", color: theme.color.textMuted, borderBottom: `1px solid ${theme.color.border}`, whiteSpace: "nowrap" } as const;
const tdStyle = { padding: "9px 10px", verticalAlign: "top", borderBottom: `1px solid ${theme.color.border}` } as const;
const tdNumericStyle = { ...tdStyle, textAlign: "right", whiteSpace: "nowrap" } as const;
const fieldStyle = { display: "flex", flexDirection: "column", gap: 5, marginTop: 10 } as const;
const dialogStyle = { padding: 14, border: `1px solid ${theme.color.accent}`, borderRadius: theme.radius.md, background: theme.color.surfaceMuted } as const;
