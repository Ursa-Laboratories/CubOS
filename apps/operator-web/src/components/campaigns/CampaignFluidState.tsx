import { useEffect, useMemo, useRef, useState } from "react";
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
import "./CampaignFluidState.css";

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

interface StateDraft {
  deckFile: string | null;
  label: string;
  seeds: FluidSeedRow[];
  tips: Record<string, boolean>;
}

function plainError(caught: unknown, fallback: string): string {
  const message = caught instanceof Error ? caught.message : typeof caught === "string" ? caught : "";
  if (!message) return fallback;
  const jsonStart = [message.indexOf("{"), message.indexOf("[")]
    .filter((index) => index >= 0)
    .sort((a, b) => a - b)[0];
  if (jsonStart === undefined) return message;
  try {
    const parsed = JSON.parse(message.slice(jsonStart)) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      const issues = parsed.detail.flatMap((item) => {
        if (typeof item === "string") return [item];
        if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") return [item.msg];
        return [];
      });
      if (issues.length > 0) return issues.join(" ");
    }
  } catch {
    return fallback;
  }
  return fallback;
}

function restoredDraft(deckFile: string | null): StateDraft {
  try {
    const saved = localStorage.getItem(DRAFT_KEY);
    if (saved) {
      const parsed = JSON.parse(saved) as Partial<StateDraft>;
      if (parsed.deckFile === deckFile && typeof parsed.label === "string" && Array.isArray(parsed.seeds)) {
        return { deckFile, label: parsed.label, seeds: parsed.seeds, tips: parsed.tips ?? {} };
      }
    }
  } catch {
    // Ignore an unavailable store or a stale draft.
  }
  return { deckFile, label: "", seeds: [], tips: {} };
}

function tipStateSummary(deck?: DeckResponse | null) {
  return (deck?.labware ?? []).flatMap((item) => {
      if (item.config.type !== "tip_rack") return [];
      const config = item.config as TipRackConfig;
      const configured = config.tip_present ?? {};
      const definedSlots = Object.keys(config.tips ?? {});
      const rows = config.rows ?? 0;
      const columns = config.columns ?? 0;
      const modelSlots = Array.from(
        { length: rows * columns },
        (_, index) => `${String.fromCharCode(65 + Math.floor(index / columns))}${(index % columns) + 1}`,
      );
      const slotIds = Array.from(new Set([...modelSlots, ...definedSlots, ...Object.keys(configured)]));
      return [{
        key: item.key,
        slots: slotIds.map((slot) => ({ key: `${item.key}.${slot}`, slot, present: configured[slot] ?? true })),
      }];
    });
}

export default function CampaignFluidState({ deckFile, deck, states, selectedId, onSelect, selectedCampaign, onCampaignAttached, suggestedContainers = [] }: Props) {
  const createState = useCreateFluidState();
  const [draft, setDraft] = useState<StateDraft>(() => restoredDraft(deckFile));
  const [error, setError] = useState<string | null>(null);
  const [reconciliationNote, setReconciliationNote] = useState("");
  const [attaching, setAttaching] = useState(false);
  const [confirmedTipFingerprint, setConfirmedTipFingerprint] = useState<string | null>(null);
  const initializedSuggestedDeck = useRef<string | null | undefined>(undefined);
  const containerOptions = useMemo(() => volumeContainerKeys(deck), [deck]);
  const tipRacks = useMemo(() => tipStateSummary(deck), [deck]);
  const selectedState = states.find((state) => state.id === selectedId) ?? null;
  const tipInventoryComplete = tipRacks.every((rack) => rack.slots.length > 0);
  const tipCount = tipRacks.reduce((total, rack) => total + rack.slots.length, 0);
  const availableTipCount = tipRacks.reduce(
    (total, rack) => total + rack.slots.filter((slot) => draft.tips[slot.key] ?? slot.present).length,
    0,
  );
  const tipFingerprint = JSON.stringify({
    deckFile,
    tips: tipRacks.flatMap((rack) => rack.slots.map((slot) => [slot.key, draft.tips[slot.key] ?? slot.present])),
  });
  const tipsConfirmed = confirmedTipFingerprint === tipFingerprint;
  const seedErrors = validateSeedRows(draft.seeds);
  const hasStartingVolumes = draft.seeds.some((row) => row.container.trim());
  const tipReviewReady = tipRacks.length === 0 || (tipInventoryComplete && tipsConfirmed);
  const createReady = hasStartingVolumes && seedErrors.length === 0 && tipReviewReady;

  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch { /* keep the in-memory draft */ }
  }, [draft]);

  useEffect(() => {
    if (draft.deckFile !== deckFile) {
      initializedSuggestedDeck.current = undefined;
      setDraft({ deckFile, label: "", seeds: [], tips: {} });
      setConfirmedTipFingerprint(null);
      return;
    }
    if (initializedSuggestedDeck.current === deckFile) return;
    initializedSuggestedDeck.current = deckFile;
    if (draft.seeds.length > 0 || suggestedContainers.length === 0) return;
    const containers = Array.from(new Set(suggestedContainers.map((item) => item.trim()).filter(Boolean)));
    if (containers.length > 0) {
      setDraft((current) => ({
        ...current,
        seeds: containers.map((container) => ({ ...createSeedRow(), container })),
      }));
    }
  }, [deckFile, draft.deckFile, draft.seeds.length, suggestedContainers]);

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
  const setRackTips = (rack: (typeof tipRacks)[number], present: boolean) => {
    setDraft((current) => ({
      ...current,
      tips: {
        ...current.tips,
        ...Object.fromEntries(rack.slots.map((slot) => [slot.key, present])),
      },
    }));
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
      setDraft({ deckFile, label: "", seeds: [], tips: {} });
      setConfirmedTipFingerprint(null);
      localStorage.removeItem(DRAFT_KEY);
    } catch (caught) {
      setError(plainError(caught, "We could not create this inventory. Check the values and try again."));
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
      setError(plainError(caught, "We could not attach this inventory to the campaign."));
    } finally {
      setAttaching(false);
    }
  };

  return (
    <section className="campaign-card campaign-state-card inventory-card" aria-labelledby="campaign-inventory-title">
      <header className="inventory-header">
        <div>
          <span className="inventory-kicker">Physical setup record</span>
          <h4 id="campaign-inventory-title">Inventory</h4>
        </div>
        <p>Choose a saved inventory or create a fresh record from what is physically loaded now.</p>
      </header>

      <section className="inventory-saved" aria-labelledby="saved-inventory-title">
        <div className="inventory-section-heading">
          <div>
            <h5 id="saved-inventory-title">Use saved inventory</h5>
            <p>This links the campaign to an existing volume and tip record.</p>
          </div>
          {selectedState && <span className="inventory-status">Selected</span>}
        </div>
        <label className="campaign-field inventory-select">
          Saved inventory
          <select aria-label="Campaign fluid state" value={selectedId ?? ""} onChange={(event) => onSelect(event.target.value ? Number(event.target.value) : null)}>
            <option value="">No inventory tracking</option>
            {states.map((state) => <option key={state.id} value={state.id}>#{state.id}{state.label ? ` — ${state.label}` : ""}</option>)}
          </select>
        </label>
        {selectedState ? (
          <div className="inventory-selected-summary">
            <strong>{selectedState.label || `Inventory #${selectedState.id}`}</strong>
            <span>Saved state #{selectedState.id}</span>
            <span>{selectedState.container_count} tracked {selectedState.container_count === 1 ? "container" : "containers"}</span>
          </div>
        ) : (
          <p className="inventory-empty">No saved inventory selected. Real campaigns require a reconciled inventory before they can start.</p>
        )}
      </section>

      {error && <div className="campaign-banner campaign-error inventory-error" role="alert">{error}</div>}

      <details className="campaign-state-create inventory-create">
        <summary>
          <span>Create a fresh fluid state</span>
          <small>Draft only until you confirm and create it</small>
        </summary>
        <div className="inventory-create-body">
          <div className="inventory-section-heading">
            <div>
              <h5>Starting volumes</h5>
              <p>Enter the volume physically loaded in each stock. Unlisted fluid containers start at 0 µL.</p>
            </div>
          </div>
          <label className="campaign-field inventory-label-field">Inventory label<input aria-label="New campaign fluid state label" value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} placeholder="Color campaign setup" /></label>
        <datalist id="campaign-fluid-containers">{containerOptions.map((key) => <option key={key} value={key} />)}</datalist>
        {draft.seeds.map((row, index) => (
          <fieldset className="campaign-seed-row" key={row.id}>
            <legend>{suggestedContainers.includes(row.container) ? "Color stock" : "Container"} {index + 1}</legend>
            <label>Container<input aria-label={`Campaign seed container ${index + 1}`} list="campaign-fluid-containers" value={row.container} onChange={(event) => updateSeed(row.id, { container: event.target.value })} placeholder="stocks.A1" /></label>
            <label>Loaded volume<div className="inventory-volume-input"><input aria-label={`Campaign seed volume ${index + 1}`} type="number" min="0" step="any" value={row.volume} onChange={(event) => updateSeed(row.id, { volume: event.target.value })} placeholder="0" /><span>µL</span></div></label>
            <button type="button" className="inventory-remove" onClick={() => updateSeeds(draft.seeds.filter((item) => item.id !== row.id))}>Remove</button>
            <details className="campaign-seed-components inventory-composition">
              <summary>Composition <span>optional</span></summary>
              {row.composition.map((component, componentIndex) => (
                <div key={component.id}>
                  <input aria-label={`Campaign seed ${index + 1} component ${componentIndex + 1} name`} value={component.component} onChange={(event) => updateSeed(row.id, { composition: row.composition.map((item) => item.id === component.id ? { ...item, component: event.target.value } : item) })} placeholder="Component" />
                  <div className="inventory-volume-input"><input aria-label={`Campaign seed ${index + 1} component ${componentIndex + 1} volume`} type="number" min="0" step="any" value={component.volume} onChange={(event) => updateSeed(row.id, { composition: row.composition.map((item) => item.id === component.id ? { ...item, volume: event.target.value } : item) })} placeholder="0" /><span>µL</span></div>
                  <button type="button" aria-label={`Remove campaign seed ${index + 1} component ${componentIndex + 1}`} onClick={() => updateSeed(row.id, { composition: row.composition.filter((item) => item.id !== component.id) })}>×</button>
                </div>
              ))}
              <button type="button" className="inventory-text-action" onClick={() => updateSeed(row.id, { composition: [...row.composition, createCompositionRow()] })}>Add component</button>
            </details>
          </fieldset>
        ))}
        <div className="campaign-actions inventory-row-actions">
          {suggestedContainers.length > 0 && <button type="button" style={theme.btn.secondary} onClick={addSuggestedSeeds}>Add color stock rows</button>}
          <button type="button" style={theme.btn.secondary} onClick={addSeed}>Add container volume</button>
        </div>
        {seedErrors.length > 0 && <div className="campaign-banner campaign-error" role="alert">{seedErrors.map((issue) => <div key={issue}>{issue}</div>)}</div>}
        <details className="campaign-tip-summary inventory-tip-check">
          <summary>
            <span>Check tip rack</span>
            <strong>{availableTipCount} of {tipCount} available</strong>
          </summary>
          <div className="inventory-tip-body">
            {tipRacks.length === 0 && <span>No tip rack is declared in this deck.</span>}
            {tipRacks.map((rack) => {
              const rackAvailable = rack.slots.filter((slot) => draft.tips[slot.key] ?? slot.present).length;
              return (
                <fieldset key={rack.key} className="campaign-tip-rack">
                  <legend>{rack.key} · {rackAvailable} of {rack.slots.length} available</legend>
                  <div className="inventory-tip-toolbar">
                    <span>Draft controls</span>
                    {rack.slots.length > 0 && <div><button type="button" onClick={() => setRackTips(rack, true)}>All loaded</button><button type="button" onClick={() => setRackTips(rack, false)}>All absent</button></div>}
                  </div>
                  {rack.slots.length > 0 && <div className="campaign-tip-grid">
                    {rack.slots.map((slot) => {
                      const present = draft.tips[slot.key] ?? slot.present;
                      return <label key={slot.key} title={`${slot.key}: ${present ? "available" : "absent"}`} data-present={present}>
                        <input type="checkbox" aria-label={`${slot.key} tip present`} checked={present} onChange={(event) => setDraft((current) => ({ ...current, tips: { ...current.tips, [slot.key]: event.target.checked } }))} />
                        {slot.slot}
                      </label>;
                    })}
                  </div>}
                </fieldset>
              );
            })}
            <p>Checked means physically loaded and available. Bulk buttons change this draft only; they never change the rack or a saved inventory.</p>
            {!tipInventoryComplete && <span className="campaign-camera-stale">Tip positions are unavailable for this deck.</span>}
          </div>
        </details>

        {tipRacks.length > 0 && tipInventoryComplete && (
          <label className="inventory-confirmation">
            <input type="checkbox" checked={tipsConfirmed} onChange={(event) => setConfirmedTipFingerprint(event.target.checked ? tipFingerprint : null)} />
            <span><strong>I verified these tip states against the physical rack</strong><small>Changing any tip resets this confirmation.</small></span>
          </label>
        )}

        <div className="inventory-create-action">
          <div>
            <strong>Create saved inventory</strong>
            <span>{!hasStartingVolumes
              ? "Enter at least one loaded container and volume."
              : !tipInventoryComplete
                ? "Load a deck with resolved tip positions before creating this inventory."
                : tipRacks.length > 0 && !tipsConfirmed
                  ? "Confirm the tip rack above before creating this inventory."
                  : "This saves a new record and selects it for the campaign. Existing saved inventories remain unchanged."}</span>
          </div>
          <button type="button" style={theme.btn.primary} onClick={() => void create()} disabled={createState.isPending || !createReady}>{createState.isPending ? "Creating…" : "Create and bind state"}</button>
        </div>
        </div>
      </details>
      {selectedCampaign && ["failed", "interrupted", "stopped"].includes(selectedCampaign.state) && selectedId !== null && selectedCampaign.spec.fluid_state_id !== selectedId && (
        <div className="campaign-state-attach">
          <strong>Attach inventory #{selectedId} to {selectedCampaign.state} campaign #{selectedCampaign.campaign_id}</strong>
          <p className="campaign-note">Describe how you matched the physical stock volumes and tips to this saved inventory. Attaching does not start or resume the campaign.</p>
          <textarea aria-label="Campaign fluid state reconciliation note" value={reconciliationNote} onChange={(event) => setReconciliationNote(event.target.value)} placeholder="Compared loaded stock volumes and consumed tips with the physical deck…" />
          <button type="button" style={theme.btn.primary} disabled={attaching || !reconciliationNote.trim()} onClick={() => void attach()}>{attaching ? "Attaching…" : "Attach state to campaign"}</button>
        </div>
      )}
    </section>
  );
}
