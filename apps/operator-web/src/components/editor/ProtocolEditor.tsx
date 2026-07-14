import { useState } from "react";
import type {
  CommandInfo,
  DeckResponse,
  GantryResponse,
  LabwareResponse,
  ProtocolStep,
  ProtocolConfig,
  ProtocolResponse,
  ProtocolRunResponse,
  InstrumentMeasurementMethods,
} from "../../types";
import { CoordinateField, NumberField, TextField, UnsavedNotice } from "./fields";
import ImportFromFile from "./ImportFromFile";
import * as theme from "../../theme";

interface Props {
  configs: string[];
  selectedFile: string | null;
  onSelectFile: (f: string) => void;
  onImportFile: (f: string) => void;
  commands: CommandInfo[];
  deck: DeckResponse;
  gantry: GantryResponse;
  instrumentMethods?: InstrumentMeasurementMethods;
  steps: ProtocolStep[] | null;
  positions?: Record<string, number[]> | null;
  /** The last-saved (server-loaded) protocol, used to reset local edits
   * when the user discards. */
  baseline?: ProtocolResponse | null;
  onSave: (filename: string, body: ProtocolConfig) => Promise<void> | void;
  /** Called on every local edit so the parent can persist the working
   * copy across tab switches. */
  onLocalChange?: (steps: ProtocolStep[]) => void;
  onPositionsChange?: (positions: Record<string, number[]> | null) => void;
  onValidate: (body: ProtocolConfig) => void;
  validationErrors: string[] | null;
  isValidating: boolean;
  onRefresh: () => void;
  onRun: () => void;
  onCancelRun: () => void;
  /** Names of configs (Gantry/Deck/Protocol) with unsaved local edits.
   * Run is blocked while non-empty because it executes the saved files,
   * not these in-memory edits. */
  unsavedConfigs: string[];
  canRun: boolean;
  runDisabledReason?: string | null;
  isRunning: boolean;
  isCancelingRun: boolean;
  runResult: ProtocolRunResponse | null;
  runError: string | null;
}

// Categorical accents for step kinds: movement = indigo accent, liquid
// handling = success emerald, scan keeps a distinct violet (the theme has
// no third categorical hue).
const COMMAND_COLORS: Record<string, string> = {
  move: theme.color.accent,
  aspirate: theme.color.success,
  dispense: theme.color.success,
  blowout: theme.color.success,
  mix: theme.color.success,
  pick_up_tip: theme.color.success,
  drop_tip: theme.color.success,
  scan: theme.categorical.violet,
};

type ProtocolChoices = {
  instruments: string[];
  plates: string[];
  positions: string[];
  instrumentTypes: Record<string, string>;
  instrumentMethods: InstrumentMeasurementMethods;
};

type EditablePosition = {
  id: string;
  name: string;
  x: number;
  y: number;
  z: number;
};

function defaultArgsForCommand(cmd: CommandInfo, choices: ProtocolChoices): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  for (const a of cmd.args) {
    const contextual = defaultArgValue(a.name, choices, args);
    if (contextual !== undefined) {
      args[a.name] = contextual;
    } else if (a.required) {
      args[a.name] = isNumericType(a.type) ? 0 : "";
    } else if (a.default != null) {
      args[a.name] = a.default;
    }
  }
  if (isAsmiIndentationStep(args, choices)) {
    args.method_kwargs = {
      step_size: 0.1,
      force_limit: 10,
      baseline_samples: 10,
      measure_with_return: false,
    };
  }
  return args;
}

export default function ProtocolEditor({
  configs,
  selectedFile,
  onSelectFile,
  onImportFile,
  commands,
  deck,
  gantry,
  instrumentMethods = {},
  steps: loadedSteps,
  positions,
  baseline,
  onSave,
  onLocalChange,
  onPositionsChange,
  onValidate,
  validationErrors,
  isValidating,
  onRefresh,
  onRun,
  onCancelRun,
  unsavedConfigs,
  canRun,
  runDisabledReason,
  isRunning,
  isCancelingRun,
  runResult,
  runError,
}: Props) {
  const [steps, setSteps] = useState<ProtocolStep[]>(() => (
    loadedSteps ? structuredClone(loadedSteps) : []
  ));
  const [positionRows, setPositionRows] = useState<EditablePosition[]>(() => (
    positionsToRows(positions)
  ));
  const [addCommand, setAddCommand] = useState(commands[0]?.name ?? "move");
  const [saveAs, setSaveAs] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const commandsByName = Object.fromEntries(commands.map((c) => [c.name, c]));
  const choices = buildProtocolChoices(deck, gantry, positionRows, instrumentMethods);
  const positionErrors = validatePositionRows(positionRows);
  const hasPositionErrors = positionErrors.length > 0;

  const commit = (next: ProtocolStep[]) => {
    setSteps(next);
    setSaveError(null);
    onLocalChange?.(next);
  };

  const commitPositions = (next: EditablePosition[]) => {
    setPositionRows(next);
    setSaveError(null);
    onPositionsChange?.(rowsToPositions(next));
  };

  const addStep = () => {
    const cmd = commandsByName[addCommand];
    if (!cmd) return;
    commit([...steps, { command: addCommand, args: defaultArgsForCommand(cmd, choices) }]);
  };

  const removeStep = (i: number) => {
    commit(steps.filter((_, idx) => idx !== i));
  };

  const moveStep = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    const next = [...steps];
    [next[i], next[j]] = [next[j], next[i]];
    commit(next);
  };

  const updateStepArg = (i: number, argName: string, value: unknown) => {
    const next = [...steps];
    const updatedArgs = { ...next[i].args, [argName]: value };
    if (argName === "instrument") {
      const methods = measurementMethodsForInstrument(String(value), choices);
      if (methods.length > 0 && !methods.includes(String(updatedArgs.method ?? ""))) {
        updatedArgs.method = methods[0];
      }
    }
    if ((argName === "instrument" || argName === "method") && isAsmiIndentationStep(updatedArgs, choices)) {
      updatedArgs.method_kwargs = {
        step_size: 0.1,
        force_limit: 10,
        baseline_samples: 10,
        measure_with_return: false,
        ...(isRecord(updatedArgs.method_kwargs) ? updatedArgs.method_kwargs : {}),
      };
    }
    if ((argName === "instrument" || argName === "method") && !isAsmiIndentationStep(updatedArgs, choices)) {
      delete updatedArgs.indentation_limit_height;
      delete updatedArgs.method_kwargs;
    }
    next[i] = { ...next[i], args: updatedArgs };
    commit(next);
  };

  const addPosition = () => {
    commitPositions([
      ...positionRows,
      {
        id: `new:${Date.now()}:${positionRows.length}`,
        name: uniquePositionName(positionRows),
        x: 0,
        y: 0,
        z: 0,
      },
    ]);
  };

  const updatePosition = (id: string, patch: Partial<Omit<EditablePosition, "id">>) => {
    const current = positionRows.find((row) => row.id === id);
    if (!current) return;
    const oldName = current.name.trim();
    const nextRows = positionRows.map((row) => (
      row.id === id ? { ...row, ...patch } : row
    ));
    commitPositions(nextRows);
    if (typeof patch.name === "string") {
      const newName = patch.name.trim();
      if (oldName && newName && oldName !== newName) {
        renamePositionReferences(oldName, newName);
      }
    }
  };

  const removePosition = (id: string) => {
    commitPositions(positionRows.filter((row) => row.id !== id));
  };

  const renamePositionReferences = (oldName: string, newName: string) => {
    let changed = false;
    const next = steps.map((step) => {
      const args = Object.fromEntries(
        Object.entries(step.args).map(([name, value]) => {
          if (isPositionArg(name) && value === oldName) {
            changed = true;
            return [name, newName];
          }
          return [name, value];
        }),
      );
      return changed ? { ...step, args } : step;
    });
    if (changed) commit(next);
  };

  const buildConfig = (): ProtocolConfig => (
    rowsToPositions(positionRows) ? { positions: rowsToPositions(positionRows), protocol: steps } : { protocol: steps }
  );

  const handleValidate = () => onValidate(buildConfig());

  const handleSave = async () => {
    const filename = saveAs.trim() || selectedFile || "";
    if (!filename || saving || hasPositionErrors) return;
    const normalized = filename.endsWith(".yaml") ? filename : filename + ".yaml";
    setSaving(true);
    try {
      await Promise.resolve(onSave(normalized, buildConfig()));
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
    if (!window.confirm("Discard unsaved protocol changes?")) return;
    setSteps(baseline?.steps ? structuredClone(baseline.steps) : []);
    setPositionRows(positionsToRows(baseline?.positions));
    setSaveError(null);
    onRefresh();
  };

  const hasSteps = steps.length > 0;
  const hasUnsaved = unsavedConfigs.length > 0;
  const protocolDirty = unsavedConfigs.includes("Protocol");
  // Deck/Gantry edits are saved in their own tabs, so the protocol-tab
  // banner only points the user there rather than asking them to save
  // those configs from here.
  const otherDirty = unsavedConfigs.filter((name) => name !== "Protocol");
  const canSave = hasSteps && (!!saveAs.trim() || !!selectedFile) && !saving && !hasPositionErrors;
  const runDisabled = isRunning || !hasSteps || !canRun || hasUnsaved;
  const runButtonTitle = hasUnsaved ? "Save your changes before running" : runDisabledReason ?? undefined;
  const runButtonLabel = isCancelingRun
    ? "Cancelling — waiting for protocol to stop"
    : isRunning
      ? "Running..."
      : "Run Protocol";

  return (
    <div>
      <div style={protocolPickerStyle}>
        <ImportFromFile configs={configs} onSelectFile={onImportFile} label="Import protocol config" />
      </div>

      {!hasSteps && (
        <div style={emptyProtocolStyle}>
          Load a protocol or add steps.
        </div>
      )}

      <div style={namedPositionsStyle}>
        <div style={namedPositionsHeaderStyle}>
          <div>
            <h3 style={sectionTitleStyle}>Named Positions</h3>
            <p style={sectionSubtextStyle}>Protocol-level targets such as park_position.</p>
          </div>
          <button onClick={addPosition} style={addBtnStyle}>
            Add Position
          </button>
        </div>

        {positionRows.length === 0 ? (
          <div style={emptyNamedPositionsStyle}>No named positions.</div>
        ) : (
          <div style={positionRowsStyle}>
            {positionRows.map((position, i) => (
              <div key={position.id} style={positionRowStyle}>
                <label style={positionNameFieldStyle}>
                  <span style={theme.fieldLabel}>Name</span>
                  <input
                    id={`pos-${i}-name`}
                    name={`pos_${i}_name`}
                    aria-label={`Position ${i + 1} name`}
                    type="text"
                    value={position.name}
                    onChange={(event) => updatePosition(position.id, { name: event.target.value })}
                    style={inputStyle}
                  />
                </label>
                <CoordinateField
                  id={`pos-${i}-coord`}
                  name={`pos_${i}_coord`}
                  label={`${position.name.trim() || `Position ${i + 1}`} coordinates`}
                  value={{ x: position.x, y: position.y, z: position.z }}
                  onChange={(value) => updatePosition(position.id, value)}
                />
                <button
                  onClick={() => removePosition(position.id)}
                  style={removeBtnStyle}
                  aria-label={`Remove ${position.name.trim() || `position ${i + 1}`}`}
                  title="Remove position"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        {positionErrors.length > 0 && (
          <div style={positionErrorStyle}>
            {positionErrors.map((error) => (
              <div key={error}>{error}</div>
            ))}
          </div>
        )}
      </div>

      {steps.map((step, i) => {
        const cmd = commandsByName[step.command];
        const color = COMMAND_COLORS[step.command] ?? theme.color.textMuted;

        return (
          <div key={i} style={{ ...cardStyle, borderLeft: `3px solid ${color}` }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <h4 style={{ margin: 0, fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
                <span style={stepBadgeStyle}>Step {i + 1}:</span>{" "}
                <span style={{ color, fontWeight: 600 }}>{step.command}</span>
              </h4>
              <div style={{ display: "flex", gap: 4 }}>
                <button onClick={() => moveStep(i, -1)} disabled={i === 0} style={reorderBtnStyle} title="Move up">
                  ↑
                </button>
                <button onClick={() => moveStep(i, 1)} disabled={i === steps.length - 1} style={reorderBtnStyle} title="Move down">
                  ↓
                </button>
                <button onClick={() => removeStep(i)} style={removeBtnStyle}>
                  ✕
                </button>
              </div>
            </div>

            {cmd ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {cmd.args.map((arg) => {
                  if (isHiddenArgForStep(arg.name, step.args, choices)) {
                    return null;
                  }
                  const val = step.args[arg.name];
                  const contextualOptions = optionsForArg(arg.name, step.args, choices);
                  const argOptions = contextualOptions.length > 0
                    ? includeCurrentOption(contextualOptions, val)
                    : [];
                  if (argOptions.length > 0) {
                    return (
                      <SmartSelectField
                        key={arg.name}
                        id={`step-${i}-${arg.name}`}
                        name={`step_${i}_${arg.name}`}
                        label={argLabel(arg.name)}
                        value={String(val ?? "")}
                        options={argOptions}
                        onChange={(v) => updateStepArg(i, arg.name, v)}
                        required={arg.required}
                      />
                    );
                  }
                  if (arg.name === "method_kwargs") {
                    return (
                      <MethodOptionsField
                        key={arg.name}
                        idPrefix={`step-${i}-method`}
                        namePrefix={`step_${i}_method`}
                        value={val}
                        asmiIndentation={isAsmiIndentationStep(step.args, choices)}
                        onChange={(v) => updateStepArg(i, arg.name, v)}
                      />
                    );
                  }
                  if (isNumericType(arg.type)) {
                    return (
                      <NumberField
                        key={arg.name}
                        id={`step-${i}-${arg.name}`}
                        name={`step_${i}_${arg.name}`}
                        label={argLabel(arg.name)}
                        value={Number(val ?? 0)}
                        onChange={(v) => updateStepArg(i, arg.name, v)}
                        required={arg.required}
                      />
                    );
                  }
                  return (
                    <TextField
                      key={arg.name}
                      id={`step-${i}-${arg.name}`}
                      name={`step_${i}_${arg.name}`}
                      label={argLabel(arg.name)}
                      value={String(val ?? "")}
                      onChange={(v) => updateStepArg(i, arg.name, v)}
                      required={arg.required}
                    />
                  );
                })}
              </div>
            ) : (
              <p style={{ color: theme.color.danger, fontSize: 12, margin: 0 }}>Unknown command: {step.command}</p>
            )}

            {validationErrors &&
              validationErrors
                .filter((e) => stepErrorPattern(i).test(e))
                .map((e, j) => (
                  <p key={j} style={{ color: theme.color.danger, fontSize: 11, margin: "4px 0 0" }}>
                    {displayStepError(e)}
                  </p>
                ))}
          </div>
        );
      })}

      <div style={addStepPanelStyle}>
        <label style={toolbarFieldStyle}>
          <span style={toolbarLabelStyle}>Add step</span>
          <select value={addCommand} onChange={(e) => setAddCommand(e.target.value)} style={selectStyle}>
            {commands.map((c) => (
              <option key={c.name} value={c.name}>
                {commandLabel(c.name)}
              </option>
            ))}
          </select>
        </label>
        <button onClick={addStep} style={addBtnStyle}>
          Add
        </button>
      </div>

      <div style={{ marginTop: 12 }}>
        {hasUnsaved && (
          <UnsavedNotice>
            <strong>Unsaved changes.</strong>{" "}
            {protocolDirty && "Save this protocol before running. "}
            {otherDirty.length > 0 && (
              `${otherDirty.join(" and ")} ${otherDirty.length > 1 ? "have" : "has"} unsaved edits — `
                + `save ${otherDirty.length > 1 ? "them in their tabs" : `it in the ${otherDirty[0]} tab`}. `
            )}
            Run Protocol uses the saved files, not your edits.
          </UnsavedNotice>
        )}
        {saveError && (
          <div style={saveErrorStyle}>Save failed: {saveError}</div>
        )}
        <div style={protocolActionBarStyle}>
          <input
            value={saveAs}
            onChange={(e) => setSaveAs(e.target.value)}
            placeholder={selectedFile ?? "my_protocol.yaml"}
            style={filenameInputStyle}
          />
          <div style={protocolButtonGroupStyle}>
            <button onClick={handleValidate} disabled={isValidating || hasPositionErrors} style={validateBtnStyle}>
              {isValidating ? "..." : "Validate"}
            </button>
            <button onClick={handleSave} disabled={!canSave} style={saveBtnStyle}>
              Save
              {protocolDirty && (
                // aria-hidden so the accessible name stays "Save"; the
                // amber asterisk is a sighted-only unsaved-edit cue.
                <span aria-hidden="true" title="Unsaved changes" style={{ marginLeft: 4, fontWeight: 700, color: theme.color.warning }}>*</span>
              )}
            </button>
            {protocolDirty && (
              <button onClick={handleDiscard} style={discardBtnStyle}>Discard changes</button>
            )}
            {isRunning && (
              <button
                onClick={onCancelRun}
                disabled={isCancelingRun}
                style={isCancelingRun ? { ...cancelRunBtnStyle, opacity: 0.65, cursor: "not-allowed" } : cancelRunBtnStyle}
              >
                {isCancelingRun ? "Cancelling..." : "Cancel Run"}
              </button>
            )}
            <button
              onClick={onRun}
              disabled={runDisabled}
              title={runButtonTitle}
              style={runDisabled ? { ...runBtnStyle, opacity: 0.5, cursor: "not-allowed" } : runBtnStyle}
            >
              {runButtonLabel}
            </button>
          </div>
        </div>

        {!hasSteps && (
          <p style={hintTextStyle}>Add at least one step before saving.</p>
        )}
        {!canRun && runDisabledReason && (
          <p style={{ ...theme.notice.warning, margin: "6px 0 0" }}>{runDisabledReason}</p>
        )}
        {validationErrors !== null && validationErrors.length === 0 && (
          <p style={{ ...theme.notice.success, margin: "6px 0 0" }}>Protocol is valid.</p>
        )}
        {validationErrors !== null && validationErrors.length > 0 && (
          <div style={{ ...theme.notice.error, margin: "6px 0 0" }}>
            {validationErrors.map((error, i) => (
              <div key={i}>{displayStepError(error)}</div>
            ))}
          </div>
        )}
        {runResult && (
          <p style={{ ...theme.notice.success, margin: "6px 0 0" }}>
            Protocol complete — {runResult.steps_executed} steps executed; campaign #{runResult.campaign_id} created.
          </p>
        )}
        {runError && (
          <p style={{ ...theme.notice.error, margin: "6px 0 0" }}>{runError}</p>
        )}
      </div>
    </div>
  );
}

function defaultArgValue(name: string, choices: ProtocolChoices, current: Record<string, unknown>): unknown {
  if (name === "instrument") return choices.instruments[0] ?? "";
  if (name === "plate") return choices.plates[0] ?? "";
  if (isPositionArg(name)) return choices.positions[0] ?? "";
  if (name === "method") {
    const instrument = String(current.instrument ?? choices.instruments[0] ?? "");
    return measurementMethodsForInstrument(instrument, choices)[0] ?? "measure";
  }
  return undefined;
}

function positionsToRows(positions: Record<string, number[]> | null | undefined): EditablePosition[] {
  return Object.entries(positions ?? {}).map(([name, value]) => ({
    id: `loaded:${name}`,
    name,
    x: finiteNumber(value[0]),
    y: finiteNumber(value[1]),
    z: finiteNumber(value[2]),
  }));
}

function rowsToPositions(rows: EditablePosition[]): Record<string, number[]> | null {
  const positions: Record<string, number[]> = {};
  for (const row of rows) {
    const name = row.name.trim();
    if (name) positions[name] = [row.x, row.y, row.z];
  }
  return Object.keys(positions).length > 0 ? positions : null;
}

function validatePositionRows(rows: EditablePosition[]): string[] {
  const errors: string[] = [];
  const seen = new Map<string, number>();
  rows.forEach((row, index) => {
    const name = row.name.trim();
    if (!name) {
      errors.push(`Position ${index + 1} needs a name.`);
    } else {
      seen.set(name, (seen.get(name) ?? 0) + 1);
    }
    if (![row.x, row.y, row.z].every(Number.isFinite)) {
      errors.push(`${name || `Position ${index + 1}`} needs numeric X, Y, and Z values.`);
    }
  });
  for (const [name, count] of seen) {
    if (count > 1) errors.push(`Position "${name}" is duplicated.`);
  }
  return errors;
}

function uniquePositionName(rows: EditablePosition[]): string {
  const existing = new Set(rows.map((row) => row.name.trim()).filter(Boolean));
  let i = 1;
  while (existing.has(`position_${i}`)) i += 1;
  return `position_${i}`;
}

function finiteNumber(value: unknown): number {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function buildProtocolChoices(
  deck: DeckResponse,
  gantry: GantryResponse,
  protocolPositions: EditablePosition[],
  instrumentMethods: InstrumentMeasurementMethods,
): ProtocolChoices {
  const instruments = Object.keys(gantry.config.instruments);
  const instrumentTypes = Object.fromEntries(
    Object.entries(gantry.config.instruments).map(([name, instrument]) => [name, instrument.type]),
  );
  const plates = deck.labware
    .filter((item) => item.config.type === "well_plate" || item.wells)
    .map((item) => item.key);
  const positions = uniqueStrings([
    ...deck.labware.flatMap(targetsForLabware),
    ...protocolPositions.map((position) => position.name.trim()),
  ]);
  return { instruments, plates, positions, instrumentTypes, instrumentMethods };
}

function targetsForLabware(item: LabwareResponse): string[] {
  const targets: string[] = [];
  const wells = item.wells ? Object.keys(item.wells).sort(wellSort) : generatedWellIds(item);
  if (wells.length > 0) {
    targets.push(...wells.map((well) => `${item.key}.${well}`));
  }
  const positions = item.positions ? Object.keys(item.positions).sort(wellSort) : [];
  if (positions.length > 0) {
    targets.push(...positions.map((position) => `${item.key}.${position}`));
  }
  if (targets.length === 0) {
    targets.push(item.key);
  }
  return targets;
}

function generatedWellIds(item: LabwareResponse): string[] {
  if (item.config.type !== "well_plate") return [];
  const rows = Math.max(0, Number(item.config.rows) || 0);
  const columns = Math.max(0, Number(item.config.columns) || 0);
  const ids: string[] = [];
  for (let row = 0; row < rows; row += 1) {
    const rowName = String.fromCharCode("A".charCodeAt(0) + row);
    for (let column = 1; column <= columns; column += 1) {
      ids.push(`${rowName}${column}`);
    }
  }
  return ids;
}

function wellSort(left: string, right: string): number {
  const a = /^([A-Za-z]+)(\d+)$/.exec(left);
  const b = /^([A-Za-z]+)(\d+)$/.exec(right);
  if (a && b && a[1] === b[1]) return Number(a[2]) - Number(b[2]);
  return left.localeCompare(right, undefined, { numeric: true });
}

function optionsForArg(
  name: string,
  args: Record<string, unknown>,
  choices: ProtocolChoices,
): string[] {
  if (name === "instrument") return choices.instruments;
  if (name === "plate") return choices.plates;
  if (isPositionArg(name)) return choices.positions;
  if (name === "method") return measurementMethodsForInstrument(String(args.instrument ?? ""), choices);
  return [];
}

function includeCurrentOption(options: string[], current: unknown): string[] {
  const value = String(current ?? "");
  if (!value || options.includes(value)) return options;
  return [value, ...options];
}

function measurementMethodsForInstrument(instrument: string, choices: ProtocolChoices): string[] {
  const type = inferInstrumentType(instrument, choices);
  const methods = choices.instrumentMethods[type] ?? [];
  if (methods.length > 0) return methods;
  if (type === "asmi") return ["indentation", "measure"];
  if (["filmetrics", "uvvis_ccs", "uv_curing"].includes(type)) return ["measure"];
  if (type === "pipette") return [];
  return ["measure"];
}

function stepErrorPattern(stepIndex: number): RegExp {
  return new RegExp(`^Step ${stepIndex}\\b`);
}

function displayStepError(error: string): string {
  return error.replace(/^Step (\d+)/, (_match, rawIndex: string) => `Step ${Number(rawIndex) + 1}`);
}

function inferInstrumentType(instrument: string, choices: ProtocolChoices): string {
  const raw = choices.instrumentTypes[instrument] ?? instrument;
  const normalized = raw.replace(/^mock_/, "").toLowerCase();
  if (normalized.includes("asmi")) return "asmi";
  if (normalized.includes("filmetrics")) return "filmetrics";
  if (normalized.includes("uvvis")) return "uvvis_ccs";
  if (normalized.includes("uv_curing")) return "uv_curing";
  if (normalized.includes("pipette")) return "pipette";
  return normalized;
}

function isPositionArg(name: string): boolean {
  return ["position", "source", "destination"].includes(name);
}

function isNumericType(type: string): boolean {
  return type.includes("float") || type.includes("int");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isAsmiIndentationStep(args: Record<string, unknown>, choices: ProtocolChoices): boolean {
  const instrument = String(args.instrument ?? "");
  const type = inferInstrumentType(instrument, choices);
  return type === "asmi" && String(args.method ?? "") === "indentation";
}

function isHiddenArgForStep(
  argName: string,
  args: Record<string, unknown>,
  choices: ProtocolChoices,
): boolean {
  return argName === "indentation_limit_height" && !isAsmiIndentationStep(args, choices);
}

function uniqueStrings(items: string[]): string[] {
  return Array.from(new Set(items.filter(Boolean)));
}

function argLabel(name: string): string {
  const labels: Record<string, string> = {
    delay_s: "Delay (s)",
    indentation_limit_height: "Indentation limit height",
    interwell_scan_height: "Interwell scan height",
    measurement_height: "Measurement height",
    method: "Measurement",
    method_kwargs: "Method options",
    volume_ul: "Volume (uL)",
  };
  return labels[name] ?? commandLabel(name);
}

function commandLabel(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function SmartSelectField({
  id,
  name,
  label,
  value,
  options,
  onChange,
  required,
}: {
  id?: string;
  name?: string;
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const isLarge = options.length > 20;
  const listId = id ? `${id}-list` : `list-${label.replace(/\s+/g, '-')}`;

  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 12 }}>
      <span style={theme.fieldLabel}>
        {label}
        {required && <span style={{ color: theme.color.danger }}> *</span>}
      </span>
      {isLarge ? (
        <>
          <input
            id={id}
            name={name}
            list={listId}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            style={selectStyle}
            required={required}
            autoComplete="off"
            placeholder="Search or select..."
          />
          <datalist id={listId}>
            {options.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
        </>
      ) : (
        <select id={id} name={name} value={value} onChange={(event) => onChange(event.target.value)} style={selectStyle} required={required}>
          {options.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      )}
    </label>
  );
}

function MethodOptionsField({
  idPrefix = "method",
  namePrefix = "method",
  value,
  asmiIndentation,
  onChange,
}: {
  idPrefix?: string;
  namePrefix?: string;
  value: unknown;
  asmiIndentation: boolean;
  onChange: (value: Record<string, unknown>) => void;
}) {
  if (!asmiIndentation) return null;
  const options = isRecord(value) ? value : {};
  const update = (key: string, nextValue: unknown) => onChange({ ...options, [key]: nextValue });
  return (
    <div style={methodOptionsStyle}>
      <div style={methodOptionsTitleStyle}>ASMI indentation options</div>
      <div style={methodOptionsGridStyle}>
        <NumberField
          id={`${idPrefix}-force-limit`}
          name={`${namePrefix}_force_limit`}
          label="Force limit (N)"
          value={Number(options.force_limit ?? 10)}
          onChange={(v) => update("force_limit", v)}
        />
        <NumberField
          id={`${idPrefix}-step-size`}
          name={`${namePrefix}_step_size`}
          label="Step size (mm)"
          value={Number(options.step_size ?? 0.1)}
          onChange={(v) => update("step_size", v)}
        />
        <NumberField
          id={`${idPrefix}-baseline-samples`}
          name={`${namePrefix}_baseline_samples`}
          label="Baseline samples"
          value={Number(options.baseline_samples ?? 10)}
          onChange={(v) => update("baseline_samples", Math.max(1, Math.round(v)))}
        />
        <SmartSelectField
          id={`${idPrefix}-measure-with-return`}
          name={`${namePrefix}_measure_with_return`}
          label="Measure with return"
          value={String(Boolean(options.measure_with_return ?? false))}
          options={["false", "true"]}
          onChange={(v) => update("measure_with_return", v === "true")}
        />
      </div>
    </div>
  );
}

const protocolPickerStyle: React.CSSProperties = {
  display: "flex",
  gap: 10,
  alignItems: "end",
  marginBottom: 12,
  flexWrap: "wrap",
};

const addStepPanelStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "end",
  gap: 8,
  minWidth: 0,
  width: "min(100%, 340px)",
  marginTop: 12,
};

const toolbarFieldStyle: React.CSSProperties = {
  display: "grid",
  gap: 4,
  flex: "1 1 220px",
  minWidth: 0,
};

const toolbarLabelStyle: React.CSSProperties = {
  ...theme.sectionLabel,
};

const methodOptionsStyle: React.CSSProperties = {
  border: `1px solid ${theme.color.accentTintBorder}`,
  background: theme.color.accentTint,
  borderRadius: theme.radius.md,
  padding: 10,
  marginTop: 4,
};

const methodOptionsTitleStyle: React.CSSProperties = {
  color: theme.color.accentText,
  fontSize: 12,
  fontWeight: 600,
  marginBottom: 8,
};

const methodOptionsGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 8,
};

const namedPositionsStyle: React.CSSProperties = {
  background: theme.color.surfaceMuted,
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.md,
  padding: 14,
  marginTop: 8,
};

const namedPositionsHeaderStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "start",
  gap: 12,
  marginBottom: 10,
};

const sectionTitleStyle: React.CSSProperties = {
  ...theme.panelTitle,
  fontSize: 13,
};

const sectionSubtextStyle: React.CSSProperties = {
  color: theme.color.textMuted,
  fontSize: 11,
  margin: "2px 0 0",
};

const positionRowsStyle: React.CSSProperties = {
  display: "grid",
  gap: 8,
};

const positionRowStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(140px, 1fr) minmax(240px, 2fr) auto",
  gap: 10,
  alignItems: "end",
};

const positionNameFieldStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  fontSize: 12,
};

const emptyNamedPositionsStyle: React.CSSProperties = {
  color: theme.color.textMuted,
  fontSize: 12,
};

const positionErrorStyle: React.CSSProperties = {
  ...theme.notice.error,
  marginTop: 8,
};

const emptyProtocolStyle: React.CSSProperties = {
  border: `1px dashed ${theme.color.borderStrong}`,
  borderRadius: theme.radius.md,
  color: theme.color.textMuted,
  fontSize: 13,
  padding: "18px 12px",
  marginTop: 8,
  background: theme.color.surfaceMuted,
};

const cardStyle: React.CSSProperties = {
  background: theme.color.surface,
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.md,
  boxShadow: theme.shadow.card,
  padding: 14,
  marginTop: 8,
};

/** Neutral index badge for step rows ("Step 1:"). */
const stepBadgeStyle: React.CSSProperties = {
  ...theme.pill,
  ...theme.mono,
  background: theme.color.surfaceSunken,
  color: theme.color.textMuted,
  fontSize: 11,
  fontWeight: 600,
};

const selectStyle: React.CSSProperties = {
  ...theme.input,
  height: 34,
  padding: "0 10px",
  width: "100%",
};

const inputStyle: React.CSSProperties = {
  ...theme.input,
};

const addBtnStyle: React.CSSProperties = {
  ...theme.btn.secondary,
  height: 34,
  padding: "0 14px",
  fontSize: 12,
};

const reorderBtnStyle: React.CSSProperties = {
  ...theme.btn.ghost,
  ...theme.btnSmall,
  padding: "2px 6px",
  lineHeight: 1,
  color: theme.color.textMuted,
};

const removeBtnStyle: React.CSSProperties = {
  ...theme.btn.danger,
  ...theme.btnSmall,
  padding: "2px 8px",
  lineHeight: 1,
};

const protocolActionBarStyle: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap",
};

const protocolButtonGroupStyle: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  justifyContent: "flex-end",
  flex: "0 0 auto",
  flexWrap: "wrap",
};

const filenameInputStyle: React.CSSProperties = {
  ...theme.input,
  flex: "1 1 220px",
  minWidth: 160,
};

const validateBtnStyle: React.CSSProperties = {
  ...theme.btn.secondary,
};

// Run is the hero action of this editor, so it alone gets btn.primary;
// Save stays a neutral secondary.
const saveBtnStyle: React.CSSProperties = {
  ...theme.btn.secondary,
  padding: "6px 20px",
};

const runBtnStyle: React.CSSProperties = {
  ...theme.btn.primary,
  padding: "6px 20px",
};

const cancelRunBtnStyle: React.CSSProperties = {
  ...theme.btn.danger,
};

const saveErrorStyle: React.CSSProperties = {
  ...theme.notice.error,
  marginBottom: 8,
};

const discardBtnStyle: React.CSSProperties = {
  ...theme.btn.ghost,
};

const hintTextStyle: React.CSSProperties = {
  marginTop: 6,
  color: theme.color.textMuted,
  fontSize: 12,
};
