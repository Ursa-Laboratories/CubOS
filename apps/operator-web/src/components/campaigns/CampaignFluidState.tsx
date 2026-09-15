import { useEffect, useMemo, useState } from "react";
import { useCreateFluidState } from "../../hooks/useFluidState";
import type { DeckResponse, FluidSeedRow, FluidStateSummary, TipRackConfig } from "../../types";
import {
  buildSeedFluids,
  createCompositionRow,
  createSeedRow,
  validateSeedRows,
  volumeContainerKeys,
} from "../../utils/fluidSeeds";
import * as theme from "../../theme";
import { campaignApi } from "./api";
import type { CampaignRecord } from "./types";

const DRAFT_KEY = "cubos.active-learning.new-fluid-state";

interface Props {
  deckFile: string | null;
  deck?: DeckResponse | null;
  states: FluidStateSummary[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  selectedCampaign?: CampaignRecord | null;
  onCampaignAttached?: (record: CampaignRecord) => void;
  suggestedContainers?: string[];
}

interface StateDraft { label: string; seeds: FluidSeedRow[]; tips: Record<string, boolean> }

function restoredDraft(): StateDraft {
  try {
    const saved = localStorage.getItem(DRAFT_KEY);
    if (saved) {
      const parsed = JSON.parse(saved) as Partial<StateDraft>;
      if (typeof parsed.label === "string" && Array.isArray(parsed.seeds)) {
        return { label: parsed.label, seeds: parsed.seeds, tips: parsed.tips ?? {} };
      }
    }
  } catch {
    // Ignore an unavailable store or a stale draft.
  }
  return { label: "", seeds: [], tips: {} };
}

function tipStateSummary(deck?: DeckResponse | null) {
  return (deck?.labware ?? []).flatMap((item) => {
      if (item.config.type !== "tip_rack") return [];
      const config = item.config as TipRackConfig;
      const configured = config.tip_present ?? {};
      const slots = Object.keys(config.tips ?? {});
      const fallbackSlots = slots.length > 0
        ? slots
        : Array.from({ length: (config.rows ?? 0) * (config.columns ?? 0) }, (_, index) => `${String.fromCharCode(65 + Math.floor(index / (config.columns ?? 1)))}${(index % (config.columns ?? 1)) + 1}`);
      const slotIds = Array.from(new Set([...fallbackSlots, ...Object.keys(configured)]));
      return [{
        key: item.key,
        slots: slotIds.map((slot) => ({ key: `${item.key}.${slot}`, slot, present: configured[slot] ?? true })),
      }];
    });
}

export default function CampaignFluidState({ deckFile, deck, states, selectedId, onSelect, selectedCampaign, onCampaignAttached, suggestedContainers = [] }: Props) {
  const createState = useCreateFluidState();
  const [draft, setDraft] = useState<StateDraft>(restoredDraft);
  const [error, setError] = useState<string | null>(null);
  const [reconciliationNote, setReconciliationNote] = useState("");
  const [attaching, setAttaching] = useState(false);
  const [confirmedTipFingerprint, setConfirmedTipFingerprint] = useState<string | null>(null);
  const containerOptions = useMemo(() => volumeContainerKeys(deck), [deck]);
  const tipRacks = useMemo(() => tipStateSummary(deck), [deck]);
  const tipInventoryComplete = tipRacks.every((rack) => rack.slots.length > 0);
  const tipFingerprint = JSON.stringify({
    deckFile,
    tips: tipRacks.flatMap((rack) => rack.slots.map((slot) => [slot.key, draft.tips[slot.key] ?? slot.present])),
  });
  const tipsConfirmed = confirmedTipFingerprint === tipFingerprint;
  const seedErrors = validateSeedRows(draft.seeds);

  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch { /* keep the in-memory draft */ }
  }, [draft]);

  const updateSeeds = (seeds: FluidSeedRow[]) => setDraft((current) => ({ ...current, seeds }));
  const addSeed = () => updateSeeds([...draft.seeds, createSeedRow()]);
  const addSuggestedSeeds = () => {
    const existing = new Set(draft.seeds.map((row) => row.container.trim()));
    const added = suggestedContainers
      .map((container) => container.trim())
      .filter((container) => container && !existing.has(container))
      .map((container) => ({ ...createSeedRow(), container }));
    updateSeeds([...draft.seeds, ...added]);
  };
  const updateSeed = (id: string, patch: Partial<Omit<FluidSeedRow, "id">>) => {
    updateSeeds(draft.seeds.map((row) => row.id === id ? { ...row, ...patch } : row));
  };

  const create = async () => {
    if (!deckFile) {
      setError("Select a deck before creating a fluid state.");
      return;
    }
    if (seedErrors.length) {
      setError("Fix the starting-volume rows before creating the state.");
      return;
    }
    if (!draft.seeds.some((row) => row.container.trim())) {
      setError("Add the containers whose starting volumes are known. Unlisted containers start at 0 µL.");
      return;
    }
    if (!tipInventoryComplete || (tipRacks.length > 0 && !tipsConfirmed)) {
      setError(!tipInventoryComplete
        ? "The selected deck does not expose resolved tip slots. Load a resolved deck before creating a campaign state."
        : "Confirm that the displayed tip states match the physical rack before creating the state.");
      return;
    }
    setError(null);
    try {
      const created = await createState.mutateAsync({
        deck_file: deckFile,
        label: draft.label.trim() || null,
        fluids: buildSeedFluids(draft.seeds),
        tips: Object.fromEntries(tipRacks.flatMap((rack) => rack.slots.map((slot) => [slot.key, draft.tips[slot.key] ?? slot.present]))),
      });
      onSelect(created.id);
      setDraft({ label: "", seeds: [], tips: {} });
      setConfirmedTipFingerprint(null);
      localStorage.removeItem(DRAFT_KEY);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const attach = async () => {
    if (!selectedCampaign || selectedId === null || !reconciliationNote.trim()) return;
    setAttaching(true);
    setError(null);
    try {
      const updated = await campaignApi.attachFluidState(selectedCampaign.campaign_id, selectedId, reconciliationNote.trim());
      onCampaignAttached?.(updated);
      setReconciliationNote("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setAttaching(false);
    }
  };

  return (
    <div className="campaign-card campaign-state-card">
      <h4>Fluid and tip state</h4>
      <p className="campaign-note">Bind an existing state, or create a fresh one for this campaign. Creating a state does not reset or change any existing state.</p>
      <label className="campaign-field">
        Campaign fluid state
        <select aria-label="Campaign fluid state" value={selectedId ?? ""} onChange={(event) => onSelect(event.target.value ? Number(event.target.value) : null)}>
          <option value="">No fluid-state tracking</option>
          {states.map((state) => <option key={state.id} value={state.id}>#{state.id}{state.label ? ` — ${state.label}` : ""}</option>)}
        </select>
      </label>

      <details className="campaign-state-create">
        <summary>Create a fresh fluid state</summary>
        <p className="campaign-note">Enter the actual loaded volume for each stock or occupied container. Every unlisted fluid container starts at 0 µL.</p>
        <label className="campaign-field">State label<input aria-label="New campaign fluid state label" value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} placeholder="Color campaign setup" /></label>
        <datalist id="campaign-fluid-containers">{containerOptions.map((key) => <option key={key} value={key} />)}</datalist>
        {draft.seeds.map((row, index) => (
          <div className="campaign-seed-row" key={row.id}>
            <input aria-label={`Campaign seed container ${index + 1}`} list="campaign-fluid-containers" value={row.container} onChange={(event) => updateSeed(row.id, { container: event.target.value })} placeholder="stocks.A1" />
            <input aria-label={`Campaign seed volume ${index + 1}`} type="number" min="0" step="any" value={row.volume} onChange={(event) => updateSeed(row.id, { volume: event.target.value })} placeholder="Loaded µL" />
            <button type="button" onClick={() => updateSeeds(draft.seeds.filter((item) => item.id !== row.id))}>Remove</button>
            <div className="campaign-seed-components">
              {row.composition.map((component, componentIndex) => (
                <div key={component.id}>
                  <input aria-label={`Campaign seed ${index + 1} component ${componentIndex + 1} name`} value={component.component} onChange={(event) => updateSeed(row.id, { composition: row.composition.map((item) => item.id === component.id ? { ...item, component: event.target.value } : item) })} placeholder="Component" />
                  <input aria-label={`Campaign seed ${index + 1} component ${componentIndex + 1} volume`} type="number" min="0" step="any" value={component.volume} onChange={(event) => updateSeed(row.id, { composition: row.composition.map((item) => item.id === component.id ? { ...item, volume: event.target.value } : item) })} placeholder="µL" />
                  <button type="button" aria-label={`Remove campaign seed ${index + 1} component ${componentIndex + 1}`} onClick={() => updateSeed(row.id, { composition: row.composition.filter((item) => item.id !== component.id) })}>×</button>
                </div>
              ))}
              <button type="button" onClick={() => updateSeed(row.id, { composition: [...row.composition, createCompositionRow()] })}>Add composition</button>
            </div>
          </div>
        ))}
        <div className="campaign-actions">
          {suggestedContainers.length > 0 && <button type="button" style={theme.btn.secondary} onClick={addSuggestedSeeds}>Add color stock rows</button>}
          <button type="button" style={theme.btn.secondary} onClick={addSeed}>Add container volume</button>
          <button type="button" style={theme.btn.primary} onClick={() => void create()} disabled={createState.isPending || seedErrors.length > 0}>{createState.isPending ? "Creating…" : "Create and bind state"}</button>
        </div>
        {seedErrors.length > 0 && <div className="campaign-banner campaign-error" role="alert">{seedErrors.map((issue) => <div key={issue}>{issue}</div>)}</div>}
        {error && <div className="campaign-banner campaign-error" role="alert">{error}</div>}
        <div className="campaign-tip-summary">
          <strong>Initial tips from the selected deck</strong>
          {tipRacks.length === 0 && <span>No tip rack is declared.</span>}
          {tipRacks.map((rack) => (
            <div key={rack.key} className="campaign-tip-rack">
              <span>{rack.key}{rack.slots.length === 0 ? ": uses the deck model defaults" : ""}</span>
              {rack.slots.length > 0 && <div className="campaign-tip-grid">
                {rack.slots.map((slot) => {
                  const present = draft.tips[slot.key] ?? slot.present;
                  return <label key={slot.key} title={`${slot.key}: ${present ? "present" : "absent"}`}>
                    <input type="checkbox" aria-label={`${slot.key} tip present`} checked={present} onChange={(event) => setDraft((current) => ({ ...current, tips: { ...current.tips, [slot.key]: event.target.checked } }))} />
                    {slot.slot}
                  </label>;
                })}
              </div>}
            </div>
          ))}
          <small>Checked means physically loaded and available; unchecked means absent or consumed. These explicit values are copied into the new state and do not edit the deck.</small>
          {tipRacks.length > 0 && tipInventoryComplete && <label><input type="checkbox" checked={tipsConfirmed} onChange={(event) => setConfirmedTipFingerprint(event.target.checked ? tipFingerprint : null)} /> I verified these tip states against the physical rack</label>}
          {!tipInventoryComplete && <span className="campaign-camera-stale">Resolved tip slots are unavailable for this deck.</span>}
        </div>
      </details>
      {selectedCampaign && ["failed", "interrupted", "stopped"].includes(selectedCampaign.state) && selectedId !== null && selectedCampaign.spec.fluid_state_id !== selectedId && (
        <div className="campaign-state-attach">
          <strong>Attach state #{selectedId} to {selectedCampaign.state} campaign #{selectedCampaign.campaign_id}</strong>
          <p className="campaign-note">Record how the physical stocks and tips were reconciled with this state. Attaching does not start or resume the campaign.</p>
          <textarea aria-label="Campaign fluid state reconciliation note" value={reconciliationNote} onChange={(event) => setReconciliationNote(event.target.value)} placeholder="Compared loaded stock volumes and consumed tips with the physical deck…" />
          <button type="button" style={theme.btn.primary} disabled={attaching || !reconciliationNote.trim()} onClick={() => void attach()}>{attaching ? "Attaching…" : "Attach state to campaign"}</button>
        </div>
      )}
    </div>
  );
}
