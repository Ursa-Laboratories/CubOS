import { useEffect, useState } from "react";
import type { DeckResponse, LabwareConfig, WellPlateConfig, VialConfig, DeckConfig } from "../../types";
import { CoordinateField, NumberField, SaveButton, TextField, UnsavedNotice } from "./fields";
import ImportFromFile from "./ImportFromFile";
import * as theme from "../../theme";

interface Props {
  configs: string[];
  selectedFile: string | null;
  onSelectFile: (f: string) => void;
  onImportFile: (f: string) => void;
  deck: DeckResponse | null;
  /** The last-saved (server-loaded) deck, used to reset local edits when
   * the user discards. Differs from `deck` when the parent is passing a
   * local working copy with unsaved edits. */
  baseline?: DeckResponse | null;
  onSave: (filename: string, body: DeckConfig) => Promise<void> | void;
  onLocalChange: (deck: DeckResponse) => void;
  /** True when this deck has local edits not yet saved to disk. The
   * prompt to save lives here (not in the Protocol tab) because this is
   * where the deck is written. */
  dirty?: boolean;
  onRefresh: () => void;
}

const EMPTY_WELL_PLATE: WellPlateConfig = {
  type: "well_plate",
  name: "",
  model_name: "",
  rows: 8,
  columns: 12,
  length: 127.76,
  width: 85.47,
  height: 14.22,
  a1: null,
  calibration: {
    a1: { x: 100.0, y: 50.0, z: 20.0 },
    a2: { x: 91.0, y: 50.0, z: 20.0 },
  },
  x_offset: 9.0,
  y_offset: 9.0,
  capacity_ul: 200.0,
  working_volume_ul: 150.0,
};

const EMPTY_VIAL: VialConfig = {
  type: "vial",
  name: "",
  model_name: "",
  height: 66.75,
  diameter: 28.0,
  location: { x: 30.0, y: 40.0, z: 20.0 },
  capacity_ul: 1500.0,
  working_volume_ul: 1200.0,
};

function buildDeckResponse(
  labware: Record<string, LabwareConfig>,
  filename: string,
  previousDeck: DeckResponse | null,
): DeckResponse {
  const previousByKey = new Map(previousDeck?.labware.map((item) => [item.key, item]));
  return {
    filename,
    labware: Object.entries(labware).map(([key, config]) => ({
      ...previousByKey.get(key),
      key,
      config,
      wells: previousByKey.get(key)?.wells ?? null,
    })),
  };
}

function isValid(labware: Record<string, LabwareConfig>): boolean {
  for (const entry of Object.values(labware)) {
    // Only validate editable types; unsupported types are preserved as-is.
    if (!isEditableDeckLabware(entry)) continue;
    if (!entry.name.trim()) return false;
  }
  return true;
}

function isEditableDeckLabware(entry: LabwareConfig): entry is WellPlateConfig | VialConfig {
  return entry.type === "well_plate" || entry.type === "vial";
}

function labwareFromDeck(deck: DeckResponse | null): Record<string, LabwareConfig> {
  const obj: Record<string, LabwareConfig> = {};
  deck?.labware.forEach((item) => {
    obj[item.key] = structuredClone(item.config);
  });
  return obj;
}

export default function DeckEditor({ configs, selectedFile, onSelectFile, onImportFile, deck, baseline, onSave, onLocalChange, dirty, onRefresh }: Props) {
  const [labware, setLabware] = useState<Record<string, LabwareConfig>>(() => labwareFromDeck(deck));
  const [saveAs, setSaveAs] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setLabware(labwareFromDeck(deck));
  }, [deck]);

  const syncViz = (next: Record<string, LabwareConfig>) => {
    setSaveError(null);
    onLocalChange(buildDeckResponse(next, selectedFile ?? "unsaved", deck));
  };

  const updateLabware = (key: string, updated: LabwareConfig) => {
    const next = { ...labware, [key]: updated };
    setLabware(next);
    syncViz(next);
  };

  const removeLabware = (key: string) => {
    const next = { ...labware };
    delete next[key];
    setLabware(next);
    syncViz(next);
  };

  const addLabware = (type: "well_plate" | "vial") => {
    // Find the next free index rather than always using
    // `count + 1` — removing an earlier item and adding a new one could
    // otherwise land on a key that's still in use (e.g. wellplate_2),
    // silently replacing that labware's calibration with a blank template.
    let idx = Object.keys(labware).length + 1;
    let key = type === "well_plate" ? `wellplate_${idx}` : `vial_${idx}`;
    while (labware[key]) {
      idx += 1;
      key = type === "well_plate" ? `wellplate_${idx}` : `vial_${idx}`;
    }
    const template = type === "well_plate" ? structuredClone(EMPTY_WELL_PLATE) : structuredClone(EMPTY_VIAL);
    template.name = key; // Pre-fill with ID
    const next = { ...labware, [key]: template };
    setLabware(next);
    syncViz(next);
  };

  const hasItems = Object.keys(labware).length > 0;
  const valid = hasItems && isValid(labware);
  const canSave = valid && (!!saveAs.trim() || !!selectedFile) && !saving;

  const handleSave = async () => {
    if (!canSave) return;
    const filename = saveAs.trim() || selectedFile || "";
    const normalized = filename.endsWith(".yaml") ? filename : `${filename}.yaml`;
    setSaving(true);
    try {
      await Promise.resolve(onSave(normalized, { labware }));
      onSelectFile(normalized);
      setSaveAs("");
      setSaveError(null);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDiscard = () => {
    if (!window.confirm("Discard unsaved deck changes?")) return;
    setLabware(labwareFromDeck(baseline ?? null));
    setSaveError(null);
    onRefresh();
  };

  return (
    <div>
      <ImportFromFile configs={configs} onSelectFile={onImportFile} label="Import deck config" />

      <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
        <button onClick={() => addLabware("well_plate")} style={addBtnStyle}>
          + Well Plate
        </button>
        <button onClick={() => addLabware("vial")} style={addBtnStyle}>
          + Vial
        </button>
      </div>

      {Object.entries(labware).map(([key, entry]) => (
        <div key={key} style={cardStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <h4 style={{ ...theme.panelTitle, ...theme.mono, fontSize: 13 }}>{key}</h4>
            <button onClick={() => removeLabware(key)} style={removeBtnStyle}>Remove</button>
          </div>
          {isEditableDeckLabware(entry) ? (
            <>
              <TextField id={`${key}-name`} name={`${key}_name`} label="Component ID" value={entry.name} onChange={(v) => updateLabware(key, { ...entry, name: v })} required />
              <TextField id={`${key}-model`} name={`${key}_model`} label="Model" value={entry.model_name} onChange={(v) => updateLabware(key, { ...entry, model_name: v })} />
              {entry.type === "well_plate" && <WellPlateFields entry={entry} onChange={(v) => updateLabware(key, v)} parentKey={key} />}
              {entry.type === "vial" && <VialFields entry={entry} onChange={(v) => updateLabware(key, v)} parentKey={key} />}
            </>
          ) : (
            <div style={unsupportedNoteStyle}>
              <strong>{entry.type}</strong> — editing not supported. This entry will be passed through to CubOS unchanged on save; the visualization updates after saving.
            </div>
          )}
        </div>
      ))}

      <div style={{ marginTop: 12 }}>
        {dirty && (
          <UnsavedNotice>
            <strong>Unsaved changes.</strong>{" "}
            Save this deck before running a protocol — runs use the saved file, not your edits.
          </UnsavedNotice>
        )}
        {saveError && (
          <div style={saveErrorStyle}>Save failed: {saveError}</div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            value={saveAs}
            onChange={(e) => setSaveAs(e.target.value)}
            placeholder={selectedFile ?? "my_deck.yaml"}
            style={filenameInputStyle}
          />
          <SaveButton
            disabled={!canSave}
            onClick={handleSave}
          />
          {dirty && (
            <button onClick={handleDiscard} style={discardBtnStyle}>Discard changes</button>
          )}
        </div>
        {!hasItems && (
          <p style={hintTextStyle}>Add at least one well plate or vial before saving.</p>
        )}
      </div>
    </div>
  );
}

function WellPlateFields({ entry, onChange, parentKey }: { entry: WellPlateConfig; onChange: (v: WellPlateConfig) => void; parentKey: string }) {
  const a1 = entry.calibration.a1 ?? entry.a1 ?? { x: 0, y: 0, z: 0 };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8 }}>
        <NumberField id={`${parentKey}-rows`} name={`${parentKey}_rows`} label="Rows" value={entry.rows} step={1} onChange={(v) => onChange({ ...entry, rows: v })} required />
        <NumberField id={`${parentKey}-cols`} name={`${parentKey}_cols`} label="Columns" value={entry.columns} step={1} onChange={(v) => onChange({ ...entry, columns: v })} required />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <NumberField id={`${parentKey}-length`} name={`${parentKey}_length`} label="Length (mm)" value={entry.length} onChange={(v) => onChange({ ...entry, length: v })} />
        <NumberField id={`${parentKey}-width`} name={`${parentKey}_width`} label="Width (mm)" value={entry.width} onChange={(v) => onChange({ ...entry, width: v })} />
        <NumberField id={`${parentKey}-height`} name={`${parentKey}_height`} label="Height (mm)" value={entry.height} onChange={(v) => onChange({ ...entry, height: v })} />
      </div>
      <CoordinateField id={`${parentKey}-a1`} name={`${parentKey}_a1`} label="Calibration A1" value={a1} onChange={(v) => onChange({ ...entry, calibration: { ...entry.calibration, a1: v } })} required />
      <CoordinateField id={`${parentKey}-a2`} name={`${parentKey}_a2`} label="Calibration A2" value={entry.calibration.a2} onChange={(v) => onChange({ ...entry, calibration: { ...entry.calibration, a2: v } })} required />
      <div style={{ display: "flex", gap: 8 }}>
        <NumberField id={`${parentKey}-xoffset`} name={`${parentKey}_xoffset`} label="Well pitch X (mm)" value={entry.x_offset} onChange={(v) => onChange({ ...entry, x_offset: v })} required />
        <NumberField id={`${parentKey}-yoffset`} name={`${parentKey}_yoffset`} label="Well pitch Y (mm)" value={entry.y_offset} onChange={(v) => onChange({ ...entry, y_offset: v })} required />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <NumberField id={`${parentKey}-capacity`} name={`${parentKey}_capacity`} label="Capacity (uL)" value={entry.capacity_ul} onChange={(v) => onChange({ ...entry, capacity_ul: v })} />
        <NumberField id={`${parentKey}-workingvol`} name={`${parentKey}_workingvol`} label="Working vol (uL)" value={entry.working_volume_ul} onChange={(v) => onChange({ ...entry, working_volume_ul: v })} />
      </div>
    </div>
  );
}

function VialFields({ entry, onChange, parentKey }: { entry: VialConfig; onChange: (v: VialConfig) => void; parentKey: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8 }}>
        <NumberField id={`${parentKey}-height`} name={`${parentKey}_height`} label="Height (mm)" value={entry.height} onChange={(v) => onChange({ ...entry, height: v })} />
        <NumberField id={`${parentKey}-diameter`} name={`${parentKey}_diameter`} label="Diameter (mm)" value={entry.diameter} onChange={(v) => onChange({ ...entry, diameter: v })} />
      </div>
      <CoordinateField id={`${parentKey}-location`} name={`${parentKey}_location`} label="Location" value={entry.location} onChange={(v) => onChange({ ...entry, location: v })} required />
      <div style={{ display: "flex", gap: 8 }}>
        <NumberField id={`${parentKey}-capacity`} name={`${parentKey}_capacity`} label="Capacity (uL)" value={entry.capacity_ul} onChange={(v) => onChange({ ...entry, capacity_ul: v })} />
        <NumberField id={`${parentKey}-workingvol`} name={`${parentKey}_workingvol`} label="Working vol (uL)" value={entry.working_volume_ul} onChange={(v) => onChange({ ...entry, working_volume_ul: v })} />
      </div>
    </div>
  );
}

/** Muted group panel for each labware item block. */
const cardStyle: React.CSSProperties = {
  background: theme.color.surfaceMuted,
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.md,
  padding: 12,
  marginTop: 8,
};

const addBtnStyle: React.CSSProperties = {
  ...theme.btn.secondary,
  ...theme.btnSmall,
};

const removeBtnStyle: React.CSSProperties = {
  ...theme.btn.danger,
  ...theme.btnSmall,
  fontSize: 11,
  padding: "2px 10px",
};

const filenameInputStyle: React.CSSProperties = {
  ...theme.input,
  ...theme.mono,
  flex: 1,
};

const unsupportedNoteStyle: React.CSSProperties = {
  ...theme.notice.warning,
  marginTop: 8,
};

const saveErrorStyle: React.CSSProperties = {
  ...theme.notice.error,
  marginBottom: 8,
};

const discardBtnStyle: React.CSSProperties = {
  ...theme.btn.secondary,
};

const hintTextStyle: React.CSSProperties = {
  marginTop: 6,
  color: theme.color.textMuted,
  fontSize: 12,
};
