import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as theme from "../../theme";
import CampaignFluidState from "./CampaignFluidState";
import CampaignCameraMonitor from "./CampaignCameraMonitor";
import ColorTargetReview from "./ColorTargetReview";
import RunPanel from "../run/RunPanel";
import { campaignApi } from "./api";
import type {
  CampaignBinding,
  CampaignPanelProps,
  CampaignPresetSummary,
  CampaignRecord,
  CampaignSpec,
  ColorTargetRun,
  ProtocolStep,
} from "./types";
import "./CampaignPanel.css";
import type { NormalizedPoint } from "../gantry/cameraGeometry";

const EDITOR_KEY = "cubos.active-learning.campaign-editor";
const TARGET_REVIEW_KEY = "cubos.active-learning.target-review";
const PRESET_WORKSPACE_KEY = "cubos.active-learning.preset-workspace";
const TERMINAL = new Set(["completed", "stopped", "failed", "interrupted"]);

function normalizePresetFilename(value: string): string {
  const trimmed = value.trim();
  return trimmed && !trimmed.toLowerCase().endsWith(".yaml") ? `${trimmed}.yaml` : trimmed;
}

function campaignErrorMessage(caught: unknown): string {
  const message = caught instanceof Error ? caught.message : String(caught);
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    return typeof parsed.detail === "string" ? parsed.detail : message;
  } catch {
    return message;
  }
}

interface BindingChoice extends CampaignBinding {
  command: string;
}

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const bindingKey = (binding: CampaignBinding) =>
  `${binding.step_index}:${binding.argument}`;

interface TargetReviewDraft {
  runId: string;
  measurement: Record<string, unknown>;
  selectedCenter: NormalizedPoint | null;
  targetWell: string;
  cameraInstrument: string;
  roiFraction: number;
  captureImageHeight: string;
  selectionNeedsAnalysis: boolean;
}

interface PresetWorkspaceDraft {
  needsFreshTarget: boolean;
  expectedFiles: { gantry: string; deck: string } | null;
  selectedPreset: string;
  presetFilename: string;
  presetName: string;
  targetWell: string;
  redSource: string;
  yellowSource: string;
  blueSource: string;
  candidateText: string;
  cameraInstrument: string;
  roiFraction: number;
  captureImageHeight: string;
  sourceProtocolFile: string;
  batchSize: number;
}

function restoredPresetWorkspace(): PresetWorkspaceDraft | null {
  try {
    const saved = localStorage.getItem(PRESET_WORKSPACE_KEY);
    if (!saved) return null;
    const parsed = JSON.parse(saved) as Partial<PresetWorkspaceDraft>;
    if (typeof parsed.needsFreshTarget !== "boolean") return null;
    return {
      needsFreshTarget: parsed.needsFreshTarget,
      expectedFiles: parsed.expectedFiles
        && typeof parsed.expectedFiles.gantry === "string"
        && typeof parsed.expectedFiles.deck === "string"
        ? parsed.expectedFiles
        : null,
      selectedPreset: typeof parsed.selectedPreset === "string" ? parsed.selectedPreset : "",
      presetFilename: typeof parsed.presetFilename === "string" ? parsed.presetFilename : "",
      presetName: typeof parsed.presetName === "string" ? parsed.presetName : "",
      targetWell: typeof parsed.targetWell === "string" ? parsed.targetWell : "plate.A1",
      redSource: typeof parsed.redSource === "string" ? parsed.redSource : "stocks.A1",
      yellowSource: typeof parsed.yellowSource === "string" ? parsed.yellowSource : "stocks.A2",
      blueSource: typeof parsed.blueSource === "string" ? parsed.blueSource : "stocks.A3",
      candidateText: typeof parsed.candidateText === "string" ? parsed.candidateText : CANDIDATE_WELLS.join(", "),
      cameraInstrument: typeof parsed.cameraInstrument === "string" ? parsed.cameraInstrument : "camera",
      roiFraction: isFiniteNumber(parsed.roiFraction) ? parsed.roiFraction : 0.5,
      captureImageHeight: typeof parsed.captureImageHeight === "string" ? parsed.captureImageHeight : "",
      sourceProtocolFile: typeof parsed.sourceProtocolFile === "string" ? parsed.sourceProtocolFile : "",
      batchSize: isFiniteNumber(parsed.batchSize) && Number.isInteger(parsed.batchSize) && parsed.batchSize > 0 ? parsed.batchSize : 6,
    };
  } catch {
    return null;
  }
}

function restoredTargetReview(): TargetReviewDraft | null {
  try {
    const saved = localStorage.getItem(TARGET_REVIEW_KEY);
    if (!saved) return null;
    const parsed = JSON.parse(saved) as Partial<TargetReviewDraft>;
    if (typeof parsed.runId !== "string" || !objectValue(parsed.measurement)) return null;
    return {
      runId: parsed.runId,
      measurement: parsed.measurement as Record<string, unknown>,
      selectedCenter: parsed.selectedCenter && isFiniteNumber(parsed.selectedCenter.x) && isFiniteNumber(parsed.selectedCenter.y)
        ? parsed.selectedCenter
        : null,
      targetWell: typeof parsed.targetWell === "string" ? parsed.targetWell : "plate.A1",
      cameraInstrument: typeof parsed.cameraInstrument === "string" ? parsed.cameraInstrument : "camera",
      roiFraction: isFiniteNumber(parsed.roiFraction) ? parsed.roiFraction : 0.5,
      captureImageHeight: typeof parsed.captureImageHeight === "string" ? parsed.captureImageHeight : "",
      selectionNeedsAnalysis: parsed.selectionNeedsAnalysis === true,
    };
  } catch {
    return null;
  }
}

function initialSpec(props: CampaignPanelProps): CampaignSpec {
  return {
    name: "",
    gantry_file: props.gantryFile ?? "",
    deck_file: props.deckFile ?? "",
    protocol_file: props.protocolFile ?? "",
    parameters: [],
    sequences: [],
    objective: { mode: "result", path: "", direction: "minimize" },
    optimizer: {
      method: "ei",
      kernel: "matern52",
      initial_trials: 3,
      initial_points: [],
      exploration: 0.05,
      seed: 7,
    },
    stop: {
      max_trials: 12,
      target_value: null,
      patience: 4,
      min_improvement: 0,
      max_seconds: null,
    },
    sum_constraint: null,
    mock_mode: true,
    fluid_state_id: null,
  };
}

function restoredSpec(props: CampaignPanelProps): CampaignSpec {
  const base = initialSpec(props);
  try {
    const saved = localStorage.getItem(EDITOR_KEY);
    if (!saved) return base;
    const parsed = JSON.parse(saved) as Partial<CampaignSpec>;
    return {
      ...base,
      ...parsed,
      objective: { ...base.objective, ...parsed.objective },
      optimizer: {
        ...base.optimizer,
        ...parsed.optimizer,
        initial_points: parsed.optimizer?.initial_points ?? [],
      },
      stop: { ...base.stop, ...parsed.stop },
    };
  } catch {
    return base;
  }
}

function leafChoices(
  value: unknown,
  path: string,
  match: (candidate: unknown) => boolean,
): string[] {
  if (match(value)) return [path];
  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      leafChoices(item, path ? `${path}.${index}` : String(index), match),
    );
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) =>
      leafChoices(item, path ? `${path}.${key}` : key, match),
    );
  }
  return [];
}

function choices(steps: ProtocolStep[], strings = false): BindingChoice[] {
  const match = strings
    ? (value: unknown) => typeof value === "string"
    : isFiniteNumber;
  return steps.flatMap((step, stepIndex) =>
    leafChoices(step.args, "", match).map((argument) => ({
      step_index: stepIndex,
      argument,
      command: step.command,
    })),
  );
}

const COLOR_INITIAL_POINTS = [
  [200, 50, 50],
  [50, 200, 50],
  [50, 50, 200],
  [125, 125, 50],
  [125, 50, 125],
  [50, 125, 125],
].map(([red, yellow, blue]) => ({ red_ul: red, yellow_ul: yellow, blue_ul: blue }));

const CANDIDATE_WELLS = [
  ...Array.from({ length: 6 }, (_, index) => `plate.A${index + 2}`),
  ...Array.from({ length: 12 }, (_, index) => `plate.B${index + 1}`),
];

const PLATE_WELLS = Array.from({ length: 96 }, (_, index) => {
  const row = String.fromCharCode(65 + Math.floor(index / 12));
  return `plate.${row}${(index % 12) + 1}`;
});

const TIP_SLOTS = Array.from({ length: 96 }, (_, index) => {
  const row = String.fromCharCode(65 + Math.floor(index / 12));
  return `tips.${row}${(index % 12) + 1}`;
});

function colorMatchingSpec(
  current: CampaignSpec,
  steps: ProtocolStep[],
): { spec: CampaignSpec; issues: string[] } {
  const transfers = steps
    .map((step, index) => ({ step, index }))
    .filter(({ step }) => step.command === "transfer")
    .slice(0, 3);
  const pickups = steps
    .map((step, index) => ({ step, index }))
    .filter(({ step }) => step.command === "pick_up_tip")
    .slice(0, 3);
  const colorMeasurement = steps.findIndex((step) => step.command === "measure_color");
  const issues: string[] = [];
  if (transfers.length < 3) {
    issues.push("The color preset needs three transfer steps: red, yellow, and blue.");
  }
  if (pickups.length < 3) {
    issues.push("The color preset needs three pick_up_tip steps for contamination control.");
  }
  if (colorMeasurement < 0) {
    issues.push("Add a measure_color step after the final mix for automatic CIEDE2000 scoring.");
  } else if (!steps[colorMeasurement].args.reference_lab) {
    issues.push("Set reference_lab on measure_color from the secret target image before validation.");
  } else if (typeof steps[colorMeasurement].args.reference_processing_profile_id !== "string") {
    issues.push("Capture and review a new target image so reference Lab and candidates share an accepted processing profile.");
  }

  const parameterNames = ["red_ul", "yellow_ul", "blue_ul"];
  const parameters = parameterNames.map((name, index) => ({
    name,
    minimum: 50,
    maximum: 200,
    step: 5,
    bindings: transfers[index]
      ? [{ step_index: transfers[index].index, argument: "volume_ul" }]
      : [],
  }));
  const destinationBindings: CampaignBinding[] = transfers.map(({ index }) => ({
    step_index: index,
    argument: "destination",
  }));
  if (colorMeasurement >= 0) {
    const lastTransfer = transfers.at(-1)?.index ?? 0;
    steps.slice(lastTransfer + 1, colorMeasurement + 1).forEach((step, offset) => {
      if ((step.command === "mix"
          || step.command === "measure_color"
          || (step.command === "move" && step.args.instrument === "camera"))
          && typeof step.args.position === "string") {
        destinationBindings.push({
          step_index: lastTransfer + 1 + offset,
          argument: "position",
        });
      }
    });
  }
  const tipSequences = pickups.map(({ index }, pickupIndex) => ({
    name: `tip_${pickupIndex + 1}`,
    values: Array.from({ length: 18 }, (_, trial) => TIP_SLOTS[trial * 3 + pickupIndex]),
    bindings: [{ step_index: index, argument: "position" }],
  }));

  return {
    issues,
    spec: {
      ...current,
      name: "CIEDE2000 color matching",
      parameters,
      sequences: [
        {
          name: "candidate_well",
          values: CANDIDATE_WELLS,
          bindings: destinationBindings,
        },
        ...tipSequences,
      ],
      objective: {
        mode: "result",
        path: colorMeasurement >= 0 ? `${colorMeasurement}.delta_e_00` : "",
        direction: "minimize",
      },
      optimizer: {
        method: "ei",
        kernel: "matern52",
        initial_trials: 6,
        initial_points: COLOR_INITIAL_POINTS,
        exploration: 0.05,
        seed: 7,
      },
      stop: {
        max_trials: 18,
        target_value: 3,
        patience: 0,
        min_improvement: 0,
        max_seconds: null,
      },
      sum_constraint: { parameters: parameterNames, total: 300 },
    },
  };
}

function TernaryPlot({ record }: { record: CampaignRecord }) {
  const names = record.spec.sum_constraint?.parameters ?? [];
  if (names.length !== 3 || !record.trials.length) return null;
  const total = record.spec.sum_constraint?.total || 1;
  const objectives = record.trials.map((trial) => trial.objective);
  const finished = objectives.filter(isFiniteNumber);
  const best = finished.length
    ? (record.spec.objective.direction === "minimize" ? Math.min : Math.max)(...finished)
    : null;
  const point = (parameters: Record<string, number | string>) => {
    const fractions = names.map((name) => Number(parameters[name]) / total);
    return {
      x: 28 * fractions[0] + 192 * fractions[1] + 110 * fractions[2],
      y: 182 * fractions[0] + 182 * fractions[1] + 22 * fractions[2],
    };
  };
  return (
    <div className="campaign-ternary" aria-label="Mixture design plot">
      <svg viewBox="0 0 220 205" role="img" aria-label="Ternary plot of tested mixtures">
        <path className="campaign-ternary-outline" d="M28 182 L192 182 L110 22 Z" />
        <text x="5" y="199">{names[0]}</text>
        <text x="166" y="199">{names[1]}</text>
        <text x="88" y="15">{names[2]}</text>
        {record.trials.map((trial) => {
          const coordinates = point(trial.parameters);
          return (
            <circle
              key={trial.index}
              cx={coordinates.x}
              cy={coordinates.y}
              r={trial.objective === best ? 6 : 4}
              className={trial.objective === best ? "campaign-ternary-best" : "campaign-ternary-point"}
            >
              <title>{`Trial ${trial.index + 1}: ${Object.entries(trial.parameters).map(([key, value]) => `${key}=${value}`).join(", ")}; objective ${trial.objective ?? "pending"}`}</title>
            </circle>
          );
        })}
      </svg>
      <span>Tested formulations · best result highlighted</span>
    </div>
  );
}

function numericTriplet(value: unknown): number[] | null {
  return Array.isArray(value)
    && value.length === 3
    && value.every(isFiniteNumber)
    ? value
    : null;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function stringValues(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function ColorReadout({ record }: { record: CampaignRecord }) {
  const measured = record.trials.filter((trial) => trial.measurement);
  if (!measured.length) return null;
  const latest = measured.at(-1)!;
  const candidates = measured.filter((trial) => isFiniteNumber(trial.objective));
  const best = candidates.reduce((current, trial) => {
    if (!current) return trial;
    const better = record.spec.objective.direction === "minimize"
      ? trial.objective! < current.objective!
      : trial.objective! > current.objective!;
    return better ? trial : current;
  }, candidates[0]);
  const targetLab = numericTriplet(latest.measurement?.reference_lab);
  const currentRgb = numericTriplet(latest.measurement?.rgb);
  const currentLab = numericTriplet(latest.measurement?.lab);
  const bestRgb = numericTriplet(best?.measurement?.rgb);
  const quality = objectValue(latest.measurement?.quality);
  const roi = objectValue(latest.measurement?.roi);
  const profile = objectValue(latest.measurement?.processing_profile);
  const identity = objectValue(latest.measurement?.well_identity);
  const measurementStatus = typeof latest.measurement?.measurement_status === "string" ? latest.measurement.measurement_status : "legacy / unverified";
  const comparisonStatus = typeof latest.measurement?.comparison_status === "string" ? latest.measurement.comparison_status : "legacy / unverified";
  const flags = stringValues(quality?.flags);
  const glare = isFiniteNumber(quality?.glare_fraction) ? quality.glare_fraction : null;
  const validFraction = isFiniteNumber(quality?.valid_fraction) ? quality.valid_fraction : null;
  const centerResidual = isFiniteNumber(roi?.center_residual_px) ? roi.center_residual_px : null;
  if (!targetLab && !currentRgb && !quality) return null;
  const formulation = best
    ? Object.entries(best.parameters).map(([key, value]) => `${key} ${value} µL`).join(" · ")
    : "—";
  return (
    <div className="campaign-color-results" aria-label="Color matching results">
      <div className="campaign-color-samples">
        {targetLab && <div><span className="campaign-swatch" style={{ backgroundColor: `lab(${targetLab[0]}% ${targetLab[1]} ${targetLab[2]})` }} /><strong>Target</strong><small>Lab {targetLab.map((value) => value.toFixed(1)).join(", ")}</small></div>}
        {currentRgb && <div><span className="campaign-swatch" style={{ backgroundColor: `rgb(${currentRgb.join(" ")})` }} /><strong>Current</strong><small>{`${isFiniteNumber(latest.objective) ? `ΔE00 ${latest.objective.toFixed(2)} · ` : ""}${currentLab ? `Estimated camera Lab ${currentLab.map((value) => value.toFixed(1)).join(", ")}` : ""}`}</small></div>}
        {bestRgb && <div><span className="campaign-swatch" style={{ backgroundColor: `rgb(${bestRgb.join(" ")})` }} /><strong>Best</strong><small>ΔE00 {best?.objective?.toFixed(2)}</small></div>}
      </div>
      <div className="campaign-color-evidence">
        <span><strong>Measurement</strong> {measurementStatus}</span>
        <span><strong>Comparison</strong> {comparisonStatus}</span>
        <span><strong>Color calibration</strong> {typeof profile?.calibration_status === "string" ? profile.calibration_status : "not reported"}</span>
        <span><strong>Expected well</strong> {typeof identity?.expected_well === "string" ? identity.expected_well : "not reported"} · not verified by CV</span>
        {centerResidual !== null && <span><strong>Detected-center residual</strong> {centerResidual.toFixed(1)} px</span>}
        {validFraction !== null && <span><strong>Valid ROI pixels</strong> {(validFraction * 100).toFixed(1)}%</span>}
        {glare !== null && <span><strong>Glare</strong> {(glare * 100).toFixed(1)}%</span>}
      </div>
      {flags.length > 0 && <div className="campaign-banner campaign-error">{flags.join(" · ")}</div>}
      <p><strong>Best formulation:</strong> {formulation}</p>
    </div>
  );
}

export default function CampaignPanel(props: CampaignPanelProps) {
  const {
    gantryFile,
    deckFile,
    protocolFile,
    protocolSteps = [],
    deck = null,
    gantry = null,
    availableFluidStates = [],
    disabledReason,
    onRunSelected,
    onCampaignChange,
  } = props;
  const numericChoices = useMemo(() => choices(protocolSteps), [protocolSteps]);
  const stringChoices = useMemo(() => choices(protocolSteps, true), [protocolSteps]);
  const protocolTargetLab = useMemo(() => {
    const measurement = protocolSteps.find((step) => step.command === "measure_color");
    return numericTriplet(measurement?.args.reference_lab);
  }, [protocolSteps]);
  const protocolTargetProfileId = useMemo(() => {
    const measurement = protocolSteps.find((step) => step.command === "measure_color");
    return typeof measurement?.args.reference_processing_profile_id === "string"
      ? measurement.args.reference_processing_profile_id
      : null;
  }, [protocolSteps]);
  const [restoredReview] = useState(restoredTargetReview);
  const [restoredPreset] = useState(restoredPresetWorkspace);
  const [restoredCampaignSpec] = useState<CampaignSpec>(() => restoredSpec(props));
  const restoredSourceProtocol = restoredPreset?.sourceProtocolFile || restoredCampaignSpec.source_protocol_file || protocolFile || "";
  const restoredBatchSize = restoredPreset?.batchSize ?? restoredCampaignSpec.batch_size ?? 6;
  const restoredColorDraft = restoredCampaignSpec.protocol_file.startsWith("ade_color_matching_")
    || Boolean(restoredCampaignSpec.source_protocol_file)
    || (restoredReview !== null && (restoredCampaignSpec.objective.path.includes("delta_e")
      || restoredCampaignSpec.sequences.some((sequence) => sequence.name === "candidate_well")));
  // TODO(iter): cover migration of a pre-batch generated color draft after tests resume.
  const restoredColorBuildMismatch = restoredColorDraft
    && (restoredCampaignSpec.source_protocol_file !== restoredSourceProtocol
      || (restoredCampaignSpec.batch_size ?? 1) !== restoredBatchSize);
  const initialNeedsFreshTarget = (restoredPreset?.needsFreshTarget ?? false)
    || (restoredReview !== null && restoredReview.measurement.measurement_status !== "accepted")
    || restoredColorBuildMismatch;
  const [spec, setSpec] = useState<CampaignSpec>(restoredCampaignSpec);
  const [activeSection, setActiveSection] = useState<"setup" | "run" | "history">("setup");
  const targetSectionRef = useRef<HTMLDivElement | null>(null);
  const targetReviewRef = useRef<HTMLDivElement | null>(null);
  const inventorySectionRef = useRef<HTMLDivElement | null>(null);
  const [presets, setPresets] = useState<CampaignPresetSummary[]>([]);
  const [selectedPreset, setSelectedPreset] = useState(restoredPreset?.selectedPreset ?? "");
  const [presetFilename, setPresetFilename] = useState(restoredPreset?.presetFilename ?? "");
  const [presetName, setPresetName] = useState(restoredPreset?.presetName ?? "");
  const [presetBusy, setPresetBusy] = useState(false);
  const [presetMessage, setPresetMessage] = useState<string | null>(null);
  const [presetError, setPresetError] = useState<string | null>(null);
  const [presetNeedsFreshTarget, setPresetNeedsFreshTarget] = useState(initialNeedsFreshTarget);
  const [presetExpectedFiles, setPresetExpectedFiles] = useState<{ gantry: string; deck: string } | null>(
    restoredPreset?.expectedFiles
      ?? (initialNeedsFreshTarget ? { gantry: restoredCampaignSpec.gantry_file, deck: restoredCampaignSpec.deck_file } : null),
  );
  const suppressHistorySelectionRef = useRef(initialNeedsFreshTarget);
  const files = useRef({ gantryFile, deckFile, protocolFile });
  const [records, setRecords] = useState<CampaignRecord[]>([]);
  const [selected, setSelected] = useState<CampaignRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [validation, setValidation] = useState<string[]>([]);
  const [observation, setObservation] = useState("");
  const [validated, setValidated] = useState(false);
  const [presetIssues, setPresetIssues] = useState<string[]>([]);
  const [targetWell, setTargetWell] = useState(restoredPreset?.targetWell ?? restoredReview?.targetWell ?? "plate.A1");
  const [redSource, setRedSource] = useState(restoredPreset?.redSource ?? "stocks.A1");
  const [yellowSource, setYellowSource] = useState(restoredPreset?.yellowSource ?? "stocks.A2");
  const [blueSource, setBlueSource] = useState(restoredPreset?.blueSource ?? "stocks.A3");
  const [candidateText, setCandidateText] = useState(restoredPreset?.candidateText ?? CANDIDATE_WELLS.join(", "));
  const [cameraInstrument, setCameraInstrument] = useState(restoredPreset?.cameraInstrument ?? restoredReview?.cameraInstrument ?? "camera");
  const [roiFraction, setRoiFraction] = useState(restoredPreset?.roiFraction ?? restoredReview?.roiFraction ?? 0.5);
  const [captureImageHeight, setCaptureImageHeight] = useState(restoredPreset?.captureImageHeight ?? restoredReview?.captureImageHeight ?? "");
  const [sourceProtocolFile, setSourceProtocolFile] = useState(restoredSourceProtocol);
  const [batchSize, setBatchSize] = useState(restoredBatchSize);
  const [targetLab, setTargetLab] = useState<number[] | null>(() => !initialNeedsFreshTarget && restoredReview?.measurement.measurement_status === "accepted" ? numericTriplet(restoredReview.measurement.lab) : null);
  const [targetRunId, setTargetRunId] = useState<string | null>(restoredReview?.runId ?? null);
  const [targetMeasurement, setTargetMeasurement] = useState<Record<string, unknown> | null>(restoredReview?.measurement ?? null);
  const [targetExpectedCenter, setTargetExpectedCenter] = useState<NormalizedPoint | null>(restoredReview?.selectedCenter ?? null);
  const [targetSelectionNeedsAnalysis, setTargetSelectionNeedsAnalysis] = useState(restoredReview?.selectionNeedsAnalysis ?? false);
  const visibleTargetLab = presetNeedsFreshTarget ? null : targetLab ?? (protocolTargetProfileId ? protocolTargetLab : null);
  const [targetBusy, setTargetBusy] = useState(false);
  const [targetStatus, setTargetStatus] = useState<string | null>(null);
  const [targetError, setTargetError] = useState<string | null>(null);
  const [targetRun, setTargetRun] = useState<ColorTargetRun | null>(null);
  const configuredCameras = Object.entries(gantry?.config.instruments ?? {})
    .filter(([, config]) => config.type === "camera")
    .map(([name]) => name);
  const loadedProtocolCamera = selected?.spec.protocol_file === protocolFile
    ? protocolSteps.find((step) => step.command === "measure_color")?.args.instrument
    : null;
  const campaignCameraInstrument = typeof loadedProtocolCamera === "string" && configuredCameras.includes(loadedProtocolCamera)
    ? loadedProtocolCamera
    : configuredCameras.length === 1 ? configuredCameras[0] : null;
  const targetParts = targetWell.split(".");
  const targetWellZ = targetParts.length === 2
    ? deck?.labware.find((item) => item.key === targetParts[0])?.wells?.[targetParts[1]]?.z ?? null
    : null;
  const cameraDepth = gantry?.config.instruments[cameraInstrument]?.depth;
  const numericCaptureHeight = captureImageHeight.trim() === "" ? null : Number(captureImageHeight);
  const captureCarriageZ = numericCaptureHeight !== null && Number.isFinite(numericCaptureHeight)
    && typeof targetWellZ === "number" && typeof cameraDepth === "number"
    ? targetWellZ + numericCaptureHeight + cameraDepth
    : null;
  const presetConfigMismatch = presetExpectedFiles !== null
    && (presetExpectedFiles.gantry !== gantryFile || presetExpectedFiles.deck !== deckFile);
  const liveCampaign = records.find((record) => !TERMINAL.has(record.state)) ?? null;
  const liveScoredSamples = liveCampaign?.trials.filter((trial) => isFiniteNumber(trial.objective) && (!trial.objective_status || trial.objective_status === "accepted")).length ?? 0;
  const liveScheduledBatches = liveCampaign ? Math.ceil(liveCampaign.trials.length / (liveCampaign.spec.batch_size || 1)) : 0;
  const candidateCount = candidateText.split(/[\n,]/).map((value) => value.trim()).filter(Boolean).length;
  const plannedSampleCount = Math.min(candidateCount, Math.max(0, spec.stop.max_trials));
  const batchCount = Number.isInteger(batchSize) && batchSize > 0 ? Math.ceil(plannedSampleCount / batchSize) : 0;
  const estimatedTipCount = batchSize === 1 ? plannedSampleCount * 3 : plannedSampleCount + batchCount * 3;
  const sourceTransfers = protocolFile === sourceProtocolFile ? protocolSteps.filter((step) => step.command === "transfer") : [];
  const sourceMix = protocolFile === sourceProtocolFile ? protocolSteps.find((step) => step.command === "mix") : null;
  const inheritedSourceHeights = Array.from(new Set(sourceTransfers.map((step) => String(step.args.source_height ?? "unspecified"))));
  const inheritedSourceHeight = inheritedSourceHeights.length === 1 ? inheritedSourceHeights[0] : inheritedSourceHeights.length > 1 ? "varies" : "not loaded";
  const inheritedMix = sourceMix
    ? `${String(sourceMix.args.volume_ul ?? "?")} µL · ${String(sourceMix.args.cycles ?? "?")} cycles · height ${String(sourceMix.args.height ?? "?")} mm`
    : "not loaded";
  const sourceProtocolMismatch = Boolean(sourceProtocolFile && protocolFile && sourceProtocolFile !== protocolFile);
  const batchError = !Number.isInteger(batchSize) || batchSize < 1 || batchSize > 6
    ? "Samples per batch must be a whole number from 1 to 6."
    : candidateCount > 0 && batchSize > candidateCount
      ? `Samples per batch (${batchSize}) cannot exceed selected candidate wells (${candidateCount}).`
      : null;
  const countConsistencyMessage = !Number.isInteger(spec.optimizer.initial_trials) || spec.optimizer.initial_trials < 1 || spec.optimizer.initial_trials > 100
    ? "Initial trials must be a whole number from 1 to 100."
    : !Number.isInteger(spec.stop.max_trials) || spec.stop.max_trials < 1 || spec.stop.max_trials > 100
      ? "Trial budget must be a whole number from 1 to 100."
      : spec.optimizer.initial_trials > spec.stop.max_trials
        ? `Initial trials (${spec.optimizer.initial_trials}) cannot exceed the trial budget (${spec.stop.max_trials}).`
        : spec.optimizer.initial_points.length > spec.optimizer.initial_trials
          ? `Initial design has ${spec.optimizer.initial_points.length} points but only ${spec.optimizer.initial_trials} initial trials.`
          : null;

  useEffect(() => localStorage.setItem(EDITOR_KEY, JSON.stringify(spec)), [spec]);
  useEffect(() => {
    localStorage.setItem(PRESET_WORKSPACE_KEY, JSON.stringify({
      needsFreshTarget: presetNeedsFreshTarget,
      expectedFiles: presetExpectedFiles,
      selectedPreset,
      presetFilename,
      presetName,
      targetWell,
      redSource,
      yellowSource,
      blueSource,
      candidateText,
      cameraInstrument,
      roiFraction,
      captureImageHeight,
      sourceProtocolFile,
      batchSize,
    } satisfies PresetWorkspaceDraft));
  }, [presetNeedsFreshTarget, presetExpectedFiles, selectedPreset, presetFilename, presetName, targetWell, redSource, yellowSource, blueSource, candidateText, cameraInstrument, roiFraction, captureImageHeight, sourceProtocolFile, batchSize]);
  const refreshPresets = useCallback(async () => {
    try {
      const next = await campaignApi.listPresets();
      setPresets(Array.isArray(next) ? next.filter((item) => typeof item?.filename === "string") : []);
    } catch (caught) {
      setPresetError(campaignErrorMessage(caught));
    }
  }, []);
  useEffect(() => { void refreshPresets(); }, [refreshPresets]);
  useEffect(() => {
    if (!targetRunId || !targetMeasurement) {
      localStorage.removeItem(TARGET_REVIEW_KEY);
      return;
    }
    localStorage.setItem(TARGET_REVIEW_KEY, JSON.stringify({
      runId: targetRunId,
      measurement: targetMeasurement,
      selectedCenter: targetExpectedCenter,
      targetWell,
      cameraInstrument,
      roiFraction,
      captureImageHeight,
      selectionNeedsAnalysis: targetSelectionNeedsAnalysis,
    } satisfies TargetReviewDraft));
  }, [targetRunId, targetMeasurement, targetExpectedCenter, targetWell, cameraInstrument, roiFraction, captureImageHeight, targetSelectionNeedsAnalysis]);
  useEffect(() => {
    if (
      files.current.gantryFile !== gantryFile
      || files.current.deckFile !== deckFile
      || files.current.protocolFile !== protocolFile
    ) {
      if (files.current.protocolFile !== protocolFile && protocolFile && (!presetExpectedFiles || !sourceProtocolFile)) {
        setSourceProtocolFile(protocolFile);
        if (files.current.protocolFile) {
          setPresetNeedsFreshTarget(true);
          setValidated(false);
        }
      }
      files.current = { gantryFile, deckFile, protocolFile };
      setSpec((current) => ({
        ...current,
        gantry_file: gantryFile ?? current.gantry_file,
        deck_file: deckFile ?? current.deck_file,
        protocol_file: protocolFile ?? current.protocol_file,
      }));
    }
  }, [gantryFile, deckFile, protocolFile, presetExpectedFiles, sourceProtocolFile]);

  const refresh = useCallback(async () => {
    try {
      const next = await campaignApi.list();
      setHistoryError(null);
      setRecords(next);
      setSelected((current) => current
        ? next.find((record) => String(record.campaign_id) === String(current.campaign_id)) ?? current
        : suppressHistorySelectionRef.current ? null : next[0] ?? null);
    } catch (caught) {
      setHistoryError(campaignErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), 3000);
    return () => clearInterval(interval);
  }, [refresh]);
  useEffect(() => onCampaignChange?.(selected), [selected, onCampaignChange]);

  const update = <Key extends keyof CampaignSpec>(key: Key, value: CampaignSpec[Key]) => {
    setValidated(false);
    setSpec((current) => ({ ...current, [key]: value }));
  };
  const invalidateBuiltCampaign = () => {
    setPresetNeedsFreshTarget(true);
    setValidated(false);
    setValidation([]);
  };
  const invalidateTargetEvidence = () => {
    invalidateBuiltCampaign();
    setTargetLab(null);
    setTargetRunId(null);
    setTargetMeasurement(null);
    setTargetExpectedCenter(null);
    setTargetSelectionNeedsAnalysis(false);
    setTargetRun(null);
    setTargetError(null);
  };
  const localErrors = () => {
    const issues: string[] = [];
    if (!spec.name.trim()) issues.push("Campaign name is required.");
    if (!spec.gantry_file || !spec.deck_file || !spec.protocol_file) {
      issues.push("Select gantry, deck, and protocol files.");
    }
    if (!spec.parameters.length) issues.push("Add at least one numeric parameter.");
    if (spec.parameters.some((parameter) =>
      !parameter.name.trim()
      || parameter.minimum >= parameter.maximum
      || parameter.step <= 0
      || !parameter.bindings.length
    )) {
      issues.push("Each parameter needs valid limits, a positive step, and a binding.");
    }
    if (countConsistencyMessage) issues.push(countConsistencyMessage);
    if (presetNeedsFreshTarget) {
      issues.push("Loaded setup requires a fresh accepted target and a newly reconciled fluid state before use.");
    }
    if (presetConfigMismatch && presetExpectedFiles) {
      issues.push(`Select gantry ${presetExpectedFiles.gantry} and deck ${presetExpectedFiles.deck} before using this setup.`);
    }
    return issues;
  };

  // TODO(iter): test preset YAML save/load and fresh target/state invalidation after the deferred hardware iteration.
  const savePreset = async () => {
    const filename = normalizePresetFilename(presetFilename);
    const name = presetName.trim() || spec.name.trim();
    if (!filename || !name) {
      setPresetError("Enter a setup filename and name before saving.");
      return;
    }
    if (!sourceProtocolFile || !protocolFile || sourceProtocolFile !== protocolFile) {
      setPresetError(`Select source protocol ${sourceProtocolFile || "03"} in the Protocol template picker before saving this color setup.`);
      return;
    }
    if (batchError) {
      setPresetError(batchError);
      return;
    }
    const imageHeight = captureImageHeight.trim() === "" ? null : Number(captureImageHeight);
    if (imageHeight !== null && !Number.isFinite(imageHeight)) {
      setPresetError("Capture image height must be a finite number or blank.");
      return;
    }
    setPresetBusy(true);
    setPresetError(null);
    setPresetMessage(null);
    try {
      const response = await campaignApi.savePreset(filename, name, { ...spec, batch_size: batchSize, source_protocol_file: sourceProtocolFile }, {
        source_protocol_file: sourceProtocolFile || protocolFile || undefined,
        batch_size: batchSize,
        target_well: targetWell,
        red_source: redSource,
        yellow_source: yellowSource,
        blue_source: blueSource,
        candidate_wells: candidateText.split(/[\n,]/).map((value) => value.trim()).filter(Boolean),
        camera_instrument: cameraInstrument,
        roi_fraction: roiFraction,
        image_height: imageHeight,
      });
      setSelectedPreset(response.filename);
      setPresetFilename(response.filename);
      setPresetName(response.preset.name);
      setPresetMessage(`Saved reusable setup ${response.filename}. Target evidence and fluid inventory were not stored.`);
      await refreshPresets();
    } catch (caught) {
      setPresetError(campaignErrorMessage(caught));
    } finally {
      setPresetBusy(false);
    }
  };

  const loadPreset = async () => {
    if (!selectedPreset) return;
    setPresetBusy(true);
    setPresetError(null);
    setPresetMessage(null);
    try {
      const response = await campaignApi.getPreset(selectedPreset);
      const loaded = response.preset;
      setSpec({ ...loaded.spec, fluid_state_id: null });
      if (loaded.color_setup) {
        setSourceProtocolFile(loaded.color_setup.source_protocol_file || loaded.spec.source_protocol_file || protocolFile || "");
        setBatchSize(loaded.color_setup.source_protocol_file || loaded.spec.source_protocol_file
          ? loaded.color_setup.batch_size ?? loaded.spec.batch_size ?? 6
          : 6);
        setTargetWell(loaded.color_setup.target_well);
        setRedSource(loaded.color_setup.red_source);
        setYellowSource(loaded.color_setup.yellow_source);
        setBlueSource(loaded.color_setup.blue_source);
        setCandidateText(loaded.color_setup.candidate_wells.join(", "));
        setCameraInstrument(loaded.color_setup.camera_instrument);
        setRoiFraction(loaded.color_setup.roi_fraction);
        setCaptureImageHeight(loaded.color_setup.image_height === null ? "" : String(loaded.color_setup.image_height));
      }
      setTargetRunId(null);
      setTargetMeasurement(null);
      setTargetExpectedCenter(null);
      setTargetSelectionNeedsAnalysis(false);
      setTargetLab(null);
      setTargetRun(null);
      setTargetError(null);
      setTargetStatus("Loaded setup. Capture and accept a fresh target, then select or create a reconciled fluid state.");
      setValidated(false);
      setValidation([]);
      setPresetIssues([]);
      setPresetNeedsFreshTarget(true);
      suppressHistorySelectionRef.current = true;
      setSelected(null);
      setPresetExpectedFiles({ gantry: loaded.spec.gantry_file, deck: loaded.spec.deck_file });
      setPresetFilename(response.filename);
      setPresetName(loaded.name);
      setPresetMessage(`Loaded ${response.filename}. No run was started.`);
    } catch (caught) {
      setPresetError(campaignErrorMessage(caught));
    } finally {
      setPresetBusy(false);
    }
  };
  const validate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await campaignApi.validate(spec);
      const issues = [...localErrors(), ...presetIssues, ...result.errors];
      setValidation(issues);
      setValidated(!issues.length && result.valid);
    } catch (caught) {
      setError(campaignErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const issues = [...localErrors(), ...presetIssues];
      if (issues.length) {
        setValidation(issues);
        return;
      }
      const record = await campaignApi.create(spec);
      suppressHistorySelectionRef.current = false;
      setSelected(record);
      setRecords((current) => [record, ...current]);
      setActiveSection("run");
    } catch (caught) {
      setError(campaignErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  const control = async (action: "pause" | "resume" | "stop" | "cancel", campaign: CampaignRecord | null = selected) => {
    if (!campaign) return;
    setBusy(true);
    try {
      const updated = await campaignApi[action](campaign.campaign_id);
      setSelected(updated);
      setRecords((current) => current.map((record) => String(record.campaign_id) === String(updated.campaign_id) ? updated : record));
      if (["running", "paused", "awaiting_observation"].includes(updated.state)) setActiveSection("run");
    } catch (caught) {
      setError(campaignErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  const applyColorPreset = () => {
    invalidateTargetEvidence();
    const preset = colorMatchingSpec(spec, protocolSteps);
    setSpec(preset.spec);
    setPresetIssues(preset.issues);
    setValidation([]);
    setValidated(false);
  };
  const readTargetAndPrepare = async () => {
    if (presetConfigMismatch && presetExpectedFiles) {
      setTargetError(`Select gantry ${presetExpectedFiles.gantry} and deck ${presetExpectedFiles.deck} before capturing this setup's target.`);
      return;
    }
    if (!gantryFile || !deckFile) {
      setError("Select the station gantry and deck before reading the target.");
      return;
    }
    const imageHeight = captureImageHeight.trim() === "" ? null : Number(captureImageHeight);
    if (imageHeight !== null && !Number.isFinite(imageHeight)) {
      setError("Capture image height must be a finite labware-relative offset in mm.");
      return;
    }
    invalidateTargetEvidence();
    setTargetBusy(true);
    setError(null);
    setTargetError(null);
    setTargetRun(null);
    setTargetStatus(`Submitting ${targetWell} target run. CubOS will preflight the complete route before any movement.`);
    let submittedRun: ColorTargetRun | null = null;
    try {
      let run = await campaignApi.readColorTarget({
        gantry_file: gantryFile,
        deck_file: deckFile,
        target_well: targetWell,
        camera_instrument: cameraInstrument,
        roi_fraction: roiFraction,
        image_height: imageHeight,
        mock_mode: false,
      });
      submittedRun = run;
      setTargetRun(run);
      setTargetStatus(`Target run ${run.run_id} is ${run.state.replaceAll("_", " ")}.`);
      while (["queued", "running", "cancel_requested"].includes(run.state)) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        run = await campaignApi.getColorTarget(run.run_id);
        submittedRun = run;
        setTargetRun(run);
        setTargetStatus(`Target run ${run.run_id} is ${run.state.replaceAll("_", " ")}.`);
      }
      if (run.state !== "succeeded") {
        const message = run.error || `Target run ended as ${run.state}.`;
        setTargetError(message);
        setTargetStatus(`Target run ${run.run_id} ${run.state}. No target image was accepted.`);
        return;
      }
      const results = (run.result as { results?: unknown[] } | null)?.results;
      const measurement = Array.isArray(results) ? results[1] as Record<string, unknown> | undefined : undefined;
      if (!measurement) throw new Error("Target run completed without analysis evidence.");
      setTargetRunId(run.run_id);
      setTargetMeasurement(measurement);
      setTargetExpectedCenter(null);
      setTargetLab(null);
      setTargetStatus(`Target frame saved from ${targetWell}. Review the image and select the intended well center before building the campaign.`);
    } catch (caught) {
      const message = campaignErrorMessage(caught);
      setTargetError(message);
      setTargetStatus(submittedRun ? `Could not refresh target run ${submittedRun.run_id}.` : "Target request was rejected before a run was created.");
    } finally {
      setTargetBusy(false);
    }
  };

  const buildFromAcceptedTarget = async () => {
    if (!sourceProtocolFile || !protocolFile || sourceProtocolFile !== protocolFile) {
      setError(`Select the saved source protocol ${sourceProtocolFile || "03"} in the Protocol template picker before building.`);
      return;
    }
    if (batchError) {
      setError(batchError);
      return;
    }
    if (countConsistencyMessage) {
      setError(countConsistencyMessage);
      return;
    }
    if (presetConfigMismatch && presetExpectedFiles) {
      setError(`Select gantry ${presetExpectedFiles.gantry} and deck ${presetExpectedFiles.deck} before building this setup.`);
      return;
    }
    if (!gantryFile || !deckFile || !targetRunId || !targetMeasurement || !targetExpectedCenter) return;
    if (targetSelectionNeedsAnalysis) {
      setError("Analyze the saved frame at the newly selected center before building the campaign.");
      return;
    }
    const lab = numericTriplet(targetMeasurement.lab);
    const profile = objectValue(targetMeasurement.processing_profile);
    const profileId = typeof profile?.id === "string" ? profile.id : null;
    const analysisRevision = isFiniteNumber(targetMeasurement.analysis_revision) ? targetMeasurement.analysis_revision : 0;
    if (targetMeasurement.measurement_status !== "accepted" || !lab || !profileId) {
      setError("The saved target frame must pass quality review and include a processing profile before the campaign can be built.");
      return;
    }
    const imageHeight = captureImageHeight.trim() === "" ? null : Number(captureImageHeight);
    const candidateWells = candidateText.split(/[\n,]/).map((value) => value.trim()).filter(Boolean);
    setTargetBusy(true);
    setError(null);
    try {
      const prepared = await campaignApi.prepareColor({
        gantry_file: gantryFile,
        deck_file: deckFile,
        source_protocol_file: sourceProtocolFile,
        batch_size: batchSize,
        target_well: targetWell,
        target_lab: lab as [number, number, number],
        red_source: redSource,
        yellow_source: yellowSource,
        blue_source: blueSource,
        candidate_wells: candidateWells,
        camera_instrument: cameraInstrument,
        roi_fraction: roiFraction,
        image_height: imageHeight,
        expected_center: [targetExpectedCenter.x, targetExpectedCenter.y],
        expected_center_source: "operator_selected",
        reference_processing_profile_id: profileId,
        target_run_id: targetRunId,
        target_analysis_revision: analysisRevision,
        fluid_state_id: spec.fluid_state_id,
        mock_mode: spec.mock_mode,
      });
      setTargetLab(lab);
      const generatedParameters = prepared.parameters.map((parameter) => {
        const prior = spec.parameters.find((item) => item.name === parameter.name);
        return prior && Number.isFinite(prior.minimum) && Number.isFinite(prior.maximum) && Number.isFinite(prior.step)
          && prior.minimum < prior.maximum && prior.step > 0 && prior.step <= prior.maximum - prior.minimum
          ? { ...parameter, minimum: prior.minimum, maximum: prior.maximum, step: prior.step }
          : parameter;
      });
      const recipeIsValid = (point: Record<string, number>) => {
        const names = generatedParameters.map((parameter) => parameter.name);
        if (Object.keys(point).length !== names.length || names.some((name) => !(name in point))) return false;
        if (!generatedParameters.every((parameter) => {
          const value = point[parameter.name];
          return Number.isFinite(value) && value >= parameter.minimum && value <= parameter.maximum
            && Math.abs((value - parameter.minimum) / parameter.step - Math.round((value - parameter.minimum) / parameter.step)) < 1e-6;
        })) return false;
        const constraint = spec.sum_constraint ?? prepared.sum_constraint;
        return !constraint || Math.abs(constraint.parameters.reduce((sum, name) => sum + point[name], 0) - constraint.total) < 1e-6;
      };
      const preserveRecipes = spec.optimizer.initial_points.length > 0
        && spec.optimizer.initial_points.length <= spec.optimizer.initial_trials
        && spec.optimizer.initial_points.every(recipeIsValid)
        && generatedParameters.length === spec.parameters.length;
      const sampleBudget = Math.min(spec.stop.max_trials, candidateCount);
      const initialTrials = Math.min(spec.optimizer.initial_trials, sampleBudget);
      const generatedRecipes = prepared.optimizer.initial_points.slice(0, initialTrials);
      const preserveBounds = preserveRecipes || generatedRecipes.every(recipeIsValid);
      setSpec((current) => ({
        ...prepared,
        name: current.name,
        parameters: preserveBounds ? generatedParameters : prepared.parameters,
        objective: prepared.objective,
        optimizer: { ...prepared.optimizer, method: current.optimizer.method, kernel: current.optimizer.kernel,
          initial_trials: initialTrials, initial_points: preserveRecipes ? current.optimizer.initial_points : generatedRecipes,
          exploration: current.optimizer.exploration, seed: current.optimizer.seed },
        stop: { ...prepared.stop, ...current.stop, max_trials: sampleBudget },
        sum_constraint: preserveBounds ? current.sum_constraint ?? prepared.sum_constraint : prepared.sum_constraint,
        mock_mode: current.mock_mode,
        fluid_state_id: current.fluid_state_id,
        batch_size: batchSize,
        source_protocol_file: sourceProtocolFile,
      }));
      setPresetIssues([]);
      setValidation([]);
      setValidated(false);
      setPresetNeedsFreshTarget(false);
      setPresetExpectedFiles(null);
      setTargetStatus(`Target read from ${targetWell}. Generated protocol ${prepared.protocol_file} is ready to validate.${preserveRecipes ? " Initial recipes were retained." : preserveBounds ? " Prior recipes did not fit the new parameter map and were replaced by generated defaults." : " Prior bounds and recipes did not fit the generated map and were replaced by compiler defaults."}`);
    } catch (caught) {
      setError(campaignErrorMessage(caught));
    } finally {
      setTargetBusy(false);
    }
  };
  const bestTrace = useMemo(() => {
    let best: number | null = null;
    return (selected?.trials ?? []).map((trial) => {
      if (
        isFiniteNumber(trial.objective)
        && (best === null || (selected?.spec.objective.direction === "minimize"
          ? trial.objective < best
          : trial.objective > best))
      ) {
        best = trial.objective;
      }
      return best;
    }).filter(isFiniteNumber);
  }, [selected]);

  const addParameter = () => {
    const choice = numericChoices[0];
    update("parameters", [
      ...spec.parameters,
      {
        name: choice?.argument.replaceAll(".", "_") ?? `parameter_${spec.parameters.length + 1}`,
        minimum: 0,
        maximum: 1,
        step: 0.1,
        bindings: choice ? [{ step_index: choice.step_index, argument: choice.argument }] : [],
      },
    ]);
  };

  const showSetupSection = (target: React.RefObject<HTMLDivElement | null>) => {
    setActiveSection("setup");
    setTimeout(() => target.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  };

  return (
    <section className="campaign-panel" style={theme.card} aria-label="Active learning campaigns">
      <div className="campaign-header">
        <div>
          <div className="campaign-kicker">{activeSection === "setup" ? "Current draft" : activeSection === "run" ? "Hardware control" : "Saved records"}</div>
          <h3 className="campaign-title">{activeSection === "setup"
            ? spec.name || "Untitled campaign"
            : activeSection === "run"
              ? liveCampaign?.spec.name || "No campaign running"
              : "Campaign history"}</h3>
          <div className="campaign-subtitle">{activeSection === "setup"
            ? `${spec.mock_mode ? "Offline mock" : "Real hardware"} · ${spec.parameters.length} parameters · ${plannedSampleCount} planned samples · ${batchCount} batches of up to ${batchSize}`
            : activeSection === "run" && liveCampaign
              ? `${liveCampaign.state.replaceAll("_", " ")} · ${liveCampaign.trials.length} samples scheduled · ${liveScoredSamples} scored · ${liveScheduledBatches} of ${Math.ceil(liveCampaign.spec.stop.max_trials / (liveCampaign.spec.batch_size || 1))} batches scheduled · best ${liveCampaign.best_objective ?? "—"}`
              : activeSection === "run"
                ? "Complete Setup to start a campaign"
                : `${records.length} saved campaign${records.length === 1 ? "" : "s"}`}</div>
        </div>
        <div className="campaign-draft-badges">
          {activeSection === "setup" && <><span>{spec.protocol_file || "No protocol"}</span><span>{spec.fluid_state_id ? `State #${spec.fluid_state_id}` : "No inventory state"}</span>{validated && <span className="campaign-success">Validated</span>}</>}
          {activeSection === "run" && liveCampaign?.active_run_id && <span>{liveCampaign.active_run_id}</span>}
          {activeSection === "history" && selected && <span>#{selected.campaign_id} · {selected.state}</span>}
        </div>
      </div>

      <nav className="campaign-inner-nav" aria-label="Campaign workspace">
        <button type="button" aria-current={activeSection === "setup" ? "page" : undefined} onClick={() => setActiveSection("setup")}>1. Setup</button>
        <button type="button" aria-current={activeSection === "run" ? "page" : undefined} onClick={() => { if (liveCampaign) setSelected(liveCampaign); setActiveSection("run"); }}>2. Run{liveCampaign ? " · active" : ""}</button>
        <button type="button" aria-current={activeSection === "history" ? "page" : undefined} onClick={() => setActiveSection("history")}>3. History{records.length ? ` · ${records.length}` : ""}</button>
      </nav>

      <div className="campaign-next-action" role="status">
        <div>
          <span>Next action</span>
          <strong>{liveCampaign
            ? `Monitor ${liveCampaign.spec.name}`
            : presetConfigMismatch && presetExpectedFiles
              ? "Select the setup files"
              : presetNeedsFreshTarget && targetMeasurement?.measurement_status === "accepted" && !targetSelectionNeedsAnalysis && !spec.mock_mode && spec.fluid_state_id === null
                ? "Select or create the current inventory"
              : presetNeedsFreshTarget && targetMeasurement?.measurement_status === "accepted" && !targetSelectionNeedsAnalysis
                ? "Build the accepted target into the campaign"
                : presetNeedsFreshTarget && targetMeasurement
                  ? `Review or recapture ${targetWell}`
                  : presetNeedsFreshTarget
                    ? `Capture and accept ${targetWell}`
                    : countConsistencyMessage
                      ? "Fix the trial counts"
                    : !validated
                      ? "Validate the current draft"
                      : "Start the validated campaign"}</strong>
          <p>{liveCampaign
            ? `${liveCampaign.trials.length} samples scheduled; ${liveScoredSamples} accepted scores so far. Hardware controls are in Run.`
            : presetConfigMismatch && presetExpectedFiles
              ? `This setup requires ${presetExpectedFiles.gantry} and ${presetExpectedFiles.deck}.`
              : presetNeedsFreshTarget && targetMeasurement?.measurement_status === "accepted" && !targetSelectionNeedsAnalysis && !spec.mock_mode && spec.fluid_state_id === null
                ? "The target is accepted. Choose the durable fluid and tip state that matches the physical deck before building."
              : presetNeedsFreshTarget
                ? "Saved settings are loaded. A fresh accepted target must be built before validation or start."
                : countConsistencyMessage ?? validation[0] ?? disabledReason ?? "The draft is ready for the next gate."}</p>
        </div>
        <div className="campaign-next-action-buttons">
          {liveCampaign ? activeSection === "run" ? null : <button type="button" style={theme.btn.primary} onClick={() => { setSelected(liveCampaign); setActiveSection("run"); }}>Open Run</button>
            : presetConfigMismatch ? <button type="button" disabled>Select required files</button>
              : presetNeedsFreshTarget && targetMeasurement?.measurement_status === "accepted" && !targetSelectionNeedsAnalysis && !spec.mock_mode && spec.fluid_state_id === null ? <button type="button" style={theme.btn.primary} onClick={() => showSetupSection(inventorySectionRef)}>Choose inventory</button>
              : presetNeedsFreshTarget && targetMeasurement?.measurement_status === "accepted" && !targetSelectionNeedsAnalysis ? <button type="button" style={theme.btn.primary} onClick={() => void buildFromAcceptedTarget()} disabled={targetBusy || !targetExpectedCenter || batchError !== null || countConsistencyMessage !== null || sourceProtocolMismatch || !sourceProtocolFile || !protocolFile || (!spec.mock_mode && spec.fluid_state_id === null)}>Build campaign</button>
                : presetNeedsFreshTarget && targetMeasurement ? <button type="button" style={theme.btn.primary} onClick={() => showSetupSection(targetReviewRef)}>Review target</button>
                  : presetNeedsFreshTarget ? <button type="button" style={theme.btn.primary} onClick={() => void readTargetAndPrepare()} disabled={targetBusy || !!disabledReason}>Capture target</button>
                    : countConsistencyMessage ? <button type="button" style={theme.btn.secondary} onClick={() => setActiveSection("setup")}>Review Advanced</button>
                    : !validated ? <button type="button" style={theme.btn.primary} onClick={() => void validate()} disabled={busy || !!disabledReason}>Validate draft</button>
                      : <button type="button" style={theme.btn.primary} onClick={() => void start()} disabled={busy || !!disabledReason}>Start campaign</button>}
        </div>
      </div>

      {activeSection === "setup" && <>
      {disabledReason && <div className="campaign-banner campaign-info">{disabledReason}</div>}
      <div className="campaign-preset-bar" aria-label="Reusable campaign setup">
        <label>Saved setup
          <select aria-label="Saved campaign setup" value={selectedPreset} onChange={(event) => {
            setSelectedPreset(event.target.value);
            const summary = presets.find((item) => item.filename === event.target.value);
            if (summary) {
              setPresetFilename(summary.filename);
              setPresetName(summary.name);
            }
          }}>
            <option value="">Choose saved YAML…</option>
            {presets.map((item) => <option key={item.filename} value={item.filename}>{item.name} · {item.filename}</option>)}
          </select>
        </label>
        <button type="button" style={theme.btn.secondary} onClick={() => void loadPreset()} disabled={!selectedPreset || presetBusy || targetBusy}>Load setup</button>
        <label>Setup filename<input aria-label="Campaign setup filename" value={presetFilename} onChange={(event) => setPresetFilename(event.target.value)} placeholder="lab-color-campaign.yaml" /></label>
        <label>Setup name<input aria-label="Campaign setup name" value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder={spec.name || "LAB color campaign"} /></label>
        <button type="button" style={theme.btn.secondary} onClick={() => void savePreset()} disabled={presetBusy}>{presetBusy ? "Working…" : "Save setup"}</button>
        <button type="button" onClick={() => void refreshPresets()} disabled={presetBusy}>Refresh</button>
        <span>Saved YAML excludes target-image evidence and live fluid/tip state.</span>
      </div>
      {presetMessage && <div className="campaign-banner campaign-success" role="status">{presetMessage}</div>}
      {presetError && <div className="campaign-banner campaign-error" role="alert">{presetError}</div>}
      {presetConfigMismatch && presetExpectedFiles && <div className="campaign-banner campaign-error" role="alert">This setup requires gantry <code>{presetExpectedFiles.gantry}</code> and deck <code>{presetExpectedFiles.deck}</code>. Select those files before capturing a fresh target. Current selection: <code>{gantryFile ?? "none"}</code> · <code>{deckFile ?? "none"}</code>.</div>}
      <div className="campaign-card campaign-essentials">
        <div className="campaign-step-heading"><span>1</span><div><h4>Experiment</h4><p>Name the draft and state what result the campaign should optimize.</p></div></div>
        <div className="campaign-fields">
          <label className="campaign-field">Name<input aria-label="Campaign name" value={spec.name} onChange={(event) => update("name", event.target.value)} /></label>
          <label className="campaign-field">Mode<select aria-label="Execution mode" value={spec.mock_mode ? "mock" : "real"} onChange={(event) => update("mock_mode", event.target.value === "mock")}><option value="mock">Offline mock (safe)</option><option value="real">Real hardware</option></select></label>
          <label className="campaign-field">Objective<select aria-label="Objective mode" value={spec.objective.mode} onChange={(event) => update("objective", { ...spec.objective, mode: event.target.value as "result" | "manual" })}><option value="result">Read from protocol result</option><option value="manual">Enter manually after each trial</option></select></label>
          <label className="campaign-field">Direction<select aria-label="Objective direction" value={spec.objective.direction} onChange={(event) => update("objective", { ...spec.objective, direction: event.target.value as "minimize" | "maximize" })}><option value="minimize">Lower is better</option><option value="maximize">Higher is better</option></select></label>
          <label className="campaign-field campaign-wide-field">Result path<input aria-label="Objective result path" value={spec.objective.path} onChange={(event) => update("objective", { ...spec.objective, path: event.target.value })} placeholder="11.delta_e_00" /></label>
        </div>
      </div>
      </>}

      {activeSection === "run" && (
        <section className="campaign-run-workspace" aria-label="Current campaign run">
          {!liveCampaign ? (
            <div className="campaign-empty-state">
              <strong>No campaign is running</strong>
              <span>Finish the setup gates before starting, or inspect a completed campaign in History.</span>
              <div className="campaign-actions"><button type="button" onClick={() => setActiveSection("setup")}>Go to Setup</button><button type="button" onClick={() => setActiveSection("history")}>Open History</button></div>
            </div>
          ) : <>
            <div className="campaign-run-header" role="status">
              <div><span>Hardware control</span><strong>{liveCampaign.spec.name}</strong></div>
              <div className="campaign-run-metrics"><span>{liveCampaign.state.replaceAll("_", " ")}</span><span>{liveCampaign.trials.length} scheduled / {liveCampaign.spec.stop.max_trials} sample budget</span><span>{liveScoredSamples} scored</span><span>{liveScheduledBatches} / {Math.ceil(liveCampaign.spec.stop.max_trials / (liveCampaign.spec.batch_size || 1))} batches scheduled</span><span>best {liveCampaign.best_objective ?? "—"}</span></div>
            </div>
            {liveCampaign.active_run_id && <RunPanel runId={liveCampaign.active_run_id} />}
            {!liveCampaign.spec.mock_mode && campaignCameraInstrument && <CampaignCameraMonitor instrument={campaignCameraInstrument} />}
            {!liveCampaign.spec.mock_mode && !campaignCameraInstrument && <div className="campaign-banner campaign-info">Load this campaign&apos;s gantry and protocol to identify its camera before opening the live monitor.</div>}
            {liveCampaign.state === "awaiting_observation" && <div className="campaign-manual-observation"><label>Manual observation<input aria-label="Manual observation" type="number" value={observation} onChange={(event) => setObservation(event.target.value)} /></label><button type="button" onClick={async () => { try { const updated = await campaignApi.observation(liveCampaign.campaign_id, Number(observation)); setSelected(updated); setRecords((current) => current.map((record) => String(record.campaign_id) === String(updated.campaign_id) ? updated : record)); setObservation(""); } catch (caught) { setError(campaignErrorMessage(caught)); } }}>Submit observation</button></div>}
            <div className="campaign-run-controls">
              <span>These controls act on the server-owned campaign.</span>
              {liveCampaign.state === "paused" && <button type="button" onClick={() => void control("resume", liveCampaign)}>Resume</button>}
              {liveCampaign.state === "running" && <button type="button" onClick={() => void control("pause", liveCampaign)}>Pause after {liveCampaign.spec.batch_size && liveCampaign.spec.batch_size > 1 ? "batch" : "trial"}</button>}
              <button type="button" onClick={() => void control("stop", liveCampaign)}>Stop after {liveCampaign.spec.batch_size && liveCampaign.spec.batch_size > 1 ? "batch" : "trial"}</button>
              <button type="button" onClick={() => void control("cancel", liveCampaign)}>Cancel active run</button>
            </div>
            {error && <div className="campaign-banner campaign-error" role="alert">{error}</div>}
          </>}
        </section>
      )}

      {activeSection === "setup" && <>

      <div className="campaign-card campaign-color-setup" ref={targetSectionRef}>
        <div className="campaign-toolbar">
          <div className="campaign-step-heading">
            <span>2</span><div>
            <h4>Color matching setup</h4>
            <p className="campaign-note">Choose the existing target and three dye stocks here. Capture and review the target before building the candidate protocol and campaign draft.</p>
            </div>
          </div>
          <button type="button" style={theme.btn.secondary} onClick={applyColorPreset}>Use loaded protocol</button>
        </div>
        <div className="campaign-fields campaign-color-fields">
          <label className="campaign-field">Source protocol template<input aria-label="Color source protocol template" value={sourceProtocolFile} readOnly placeholder="Select protocol 03 above" /></label>
          <label className="campaign-field">Samples per batch<input aria-label="Color samples per batch" type="number" min="1" max="6" step="1" value={batchSize} onChange={(event) => { setBatchSize(Number(event.target.value)); invalidateBuiltCampaign(); }} /></label>
          <label className="campaign-field">Target well<select aria-label="Target well" value={targetWell} onChange={(event) => { setTargetWell(event.target.value); invalidateTargetEvidence(); }}>{PLATE_WELLS.map((well) => <option key={well}>{well}</option>)}</select></label>
          <label className="campaign-field">Red stock<input aria-label="Red stock" value={redSource} onChange={(event) => { setRedSource(event.target.value); invalidateBuiltCampaign(); }} /></label>
          <label className="campaign-field">Yellow stock<input aria-label="Yellow stock" value={yellowSource} onChange={(event) => { setYellowSource(event.target.value); invalidateBuiltCampaign(); }} /></label>
          <label className="campaign-field">Blue stock<input aria-label="Blue stock" value={blueSource} onChange={(event) => { setBlueSource(event.target.value); invalidateBuiltCampaign(); }} /></label>
          <label className="campaign-field">Camera<input aria-label="Color camera" value={cameraInstrument} onChange={(event) => { setCameraInstrument(event.target.value); invalidateTargetEvidence(); }} /></label>
          <label className="campaign-field">Sample radius / detected well radius<input aria-label="Color ROI fraction" type="number" min="0.1" max="1" step="0.05" value={roiFraction} onChange={(event) => { setRoiFraction(Number(event.target.value)); invalidateTargetEvidence(); }} /></label>
          <label className="campaign-field">Capture height relative to well (mm)<input aria-label="Color capture image height" type="number" step="0.5" value={captureImageHeight} onChange={(event) => { setCaptureImageHeight(event.target.value); invalidateTargetEvidence(); }} placeholder="Use configured ceiling" /></label>
          <label className="campaign-field campaign-candidate-field">Candidate wells <span>{candidateCount} selected</span><textarea aria-label="Color candidate wells" value={candidateText} onChange={(event) => { setCandidateText(event.target.value); invalidateBuiltCampaign(); }} /></label>
        </div>
        <p className="campaign-note">Capture height is relative to the calibrated well surface: positive is above it and negative is below. Blank preserves the existing configured ceiling. CubOS validates the selected height against the calibrated labware, working volume, and collision plan, then retracts to the configured planning ceiling.</p>
        {captureCarriageZ !== null && <p className="campaign-note">Preview: {targetWell} surface Z {targetWellZ?.toFixed(3)} mm + image height {numericCaptureHeight?.toFixed(3)} mm + camera depth {cameraDepth?.toFixed(3)} mm = carriage Z {captureCarriageZ.toFixed(3)} mm. Review physical camera clearance before running.</p>}
        <p className="campaign-note">After capture, select the intended well center on the saved image. Computer vision may locate a well-like circle near it, but cannot verify the well identity.</p>
        <div className="campaign-color-limits">{candidateCount} candidate wells · {plannedSampleCount} planned samples → {batchCount} native batch runs at up to {batchSize} samples each. Trial budget counts samples, not batches. {batchSize > 1 ? "Each batch dispenses color by color across its wells, then mixes and measures each well." : "Each sample runs the source sequence separately."} Estimated tips: {estimatedTipCount} ({batchSize === 1 ? "three dye tips per sample, with the final dye tip used for mixing" : `${batchCount * 3} dye tips, one per color per batch, plus ${plannedSampleCount} dedicated mix tips`}). Inherited from {sourceProtocolFile || "the selected source protocol"}: source height {inheritedSourceHeight} mm; mix {inheritedMix}. The generated protocol is separate from this saved template.</div>
        {sourceProtocolMismatch && <div className="campaign-banner campaign-error" role="alert">Select source protocol {sourceProtocolFile} in the Protocol template picker before building. Current selection: {protocolFile}.</div>}
        {batchError && <div className="campaign-banner campaign-error" role="alert">{batchError}</div>}
        <div className="campaign-actions">
          <button type="button" style={theme.btn.primary} onClick={() => void readTargetAndPrepare()} disabled={targetBusy || !!disabledReason || presetConfigMismatch}>{targetBusy ? "Capturing target…" : `Capture ${targetWell} target for review`}</button>
          {visibleTargetLab && <span className="campaign-target-chip"><span className="campaign-swatch" style={{ backgroundColor: `lab(${visibleTargetLab[0]}% ${visibleTargetLab[1]} ${visibleTargetLab[2]})` }} />Target Lab {visibleTargetLab.map((value) => value.toFixed(4)).join(", ")}</span>}
          {visibleTargetLab && !presetNeedsFreshTarget && <span className="campaign-note">Generated protocol: {spec.protocol_file}. {protocolFile && protocolFile !== spec.protocol_file ? `Base template ${protocolFile} remains unchanged.` : ""}</span>}
          {presetNeedsFreshTarget && !targetMeasurement && <span className="campaign-note">Loaded setup intentionally cleared target evidence. Capture and accept a fresh reference before use.</span>}
          {!presetNeedsFreshTarget && !visibleTargetLab && protocolTargetLab && <span className="campaign-note">The loaded protocol contains a legacy reference Lab without accepted processing-profile provenance. Capture a new target before use.</span>}
          {targetStatus && <span className="campaign-note">{targetStatus}</span>}
        </div>
        <div className="campaign-capture-setup">
          <strong>Capture setup</strong>
          <code>{gantryFile ?? "No gantry selected"}</code>
          <span>·</span>
          <code>{deckFile ?? "No deck selected"}</code>
        </div>
        {(targetRun || targetError) && (
          <div className="campaign-target-run" role="status">
            {targetRun && <>
              <span className={`campaign-target-run-state campaign-target-run-${targetRun.state}`}>{targetRun.state.replaceAll("_", " ")}</span>
              <code>{targetRun.run_id}</code>
              <button type="button" onClick={() => onRunSelected?.(targetRun.run_id)}>Open run</button>
            </>}
            {targetError && <div className="campaign-banner campaign-error" role="alert">{targetError}</div>}
          </div>
        )}
      </div>
      {targetRun && ["queued", "running", "cancel_requested"].includes(targetRun.state) && (
        <div className="campaign-target-progress">
          <RunPanel runId={targetRun.run_id} />
        </div>
      )}
      {targetRunId && targetMeasurement && (
        <div className="campaign-review-step" ref={targetReviewRef}><div className="campaign-step-heading"><span>3</span><div><h4>Review target</h4><p>Confirm the intended well region and resolve image-quality warnings before building.</p></div></div><ColorTargetReview
          key={targetRunId}
          runId={targetRunId}
          expectedWell={targetWell}
          measurement={targetMeasurement}
          selectedCenter={targetExpectedCenter}
          selectionNeedsAnalysis={targetSelectionNeedsAnalysis}
          onSelectedCenter={(point) => { setTargetExpectedCenter(point); setTargetSelectionNeedsAnalysis(true); invalidateBuiltCampaign(); }}
          onMeasurement={(measurement) => {
            setTargetMeasurement(measurement);
            setTargetSelectionNeedsAnalysis(false);
            const lab = numericTriplet(measurement.lab);
            setTargetLab(measurement.measurement_status === "accepted" ? lab : null);
            setTargetStatus(measurement.measurement_status === "accepted"
              ? "Saved target frame passed quality review. Build the campaign when the physical setup is ready."
              : "Saved target frame remains rejected. Review the diagnostics, adjust the selected center, and analyze the same frame again.");
          }}
        /></div>
      )}
      {targetRunId && targetMeasurement?.measurement_status === "accepted" && (
        <div className="campaign-actions">
          <button type="button" style={theme.btn.primary} onClick={() => void buildFromAcceptedTarget()} disabled={targetBusy || !targetExpectedCenter || targetSelectionNeedsAnalysis || presetConfigMismatch || batchError !== null || countConsistencyMessage !== null || sourceProtocolMismatch || !sourceProtocolFile || !protocolFile || (!spec.mock_mode && spec.fluid_state_id === null)}>Build campaign from accepted target</button>
          {!spec.mock_mode && spec.fluid_state_id === null && <span className="campaign-note">Create or select a reconciled fluid state before building a real color campaign.</span>}
        </div>
      )}
      {presetIssues.length > 0 && (
        <div className="campaign-banner campaign-info">
          {presetIssues.map((issue) => <div key={issue}>{issue}</div>)}
        </div>
      )}

      <div className="campaign-grid">
        <div className="campaign-inventory-step" ref={inventorySectionRef}><div className="campaign-step-heading"><span>4</span><div><h4>Inventory</h4><p>Select the current durable fluid and tip state for this draft.</p></div></div>
        <CampaignFluidState
          deckFile={deckFile}
          deck={deck}
          states={availableFluidStates}
          selectedId={spec.fluid_state_id}
          onSelect={(id) => update("fluid_state_id", id)}
          suggestedContainers={[redSource, yellowSource, blueSource]}
        />
        </div>
      </div>

      <details className="campaign-advanced" open={countConsistencyMessage ? true : undefined}>
        <summary>
          <span>Advanced campaign design</span>
          <small>{spec.parameters.length} parameters · {spec.optimizer.initial_points.length} design points · {spec.sequences.length} sequences</small>
        </summary>
        <div className="campaign-advanced-content">
        {countConsistencyMessage && <div className="campaign-banner campaign-error" role="alert">{countConsistencyMessage}</div>}
        <div className="campaign-grid">
        <div className="campaign-card">
          <h4>Learning strategy</h4>
          <div className="campaign-fields">
            <label className="campaign-field">Acquisition<select aria-label="Optimizer method" value={spec.optimizer.method} onChange={(event) => update("optimizer", { ...spec.optimizer, method: event.target.value as "ei" | "lcb" | "random" })}><option value="ei">Expected improvement</option><option value="lcb">Lower confidence bound</option><option value="random">Random / DOE only</option></select></label>
            <label className="campaign-field">GP kernel<select aria-label="GP kernel" value={spec.optimizer.kernel} onChange={(event) => update("optimizer", { ...spec.optimizer, kernel: event.target.value as "matern52" | "rbf" })}><option value="matern52">Matérn 5/2</option><option value="rbf">RBF</option></select></label>
            <label className="campaign-field">Initial trials<input aria-label="Initial trials" type="number" min="1" max="100" step="1" value={spec.optimizer.initial_trials} onChange={(event) => update("optimizer", { ...spec.optimizer, initial_trials: Number(event.target.value) })} /></label>
            <label className="campaign-field">Exploration<input aria-label="Exploration" type="number" min="0" max="10" step="0.01" value={spec.optimizer.exploration} onChange={(event) => update("optimizer", { ...spec.optimizer, exploration: Number(event.target.value) })} /></label>
            <label className="campaign-field">Seed<input aria-label="Optimizer seed" type="number" min="0" max="2147483647" step="1" value={spec.optimizer.seed} onChange={(event) => update("optimizer", { ...spec.optimizer, seed: Number(event.target.value) })} /></label>
          </div>
        </div>
        <div className="campaign-card">
          <h4>Stop limits</h4>
          <p className="campaign-note">Trial budget counts samples. Limits are checked between completed batches; Cancel interrupts the active native run.</p>
          <div className="campaign-fields">
            {(["max_trials", "patience", "min_improvement", "max_seconds", "target_value"] as const).map((key) => (
              <label className="campaign-field" key={key}>{key.replaceAll("_", " ")}<input aria-label={key.replaceAll("_", " ")} type="number" min={key === "max_trials" ? 1 : key === "patience" || key === "min_improvement" ? 0 : key === "max_seconds" ? 0.001 : undefined} max={key === "max_trials" || key === "patience" ? 100 : key === "max_seconds" ? 604800 : undefined} step={key === "max_trials" || key === "patience" ? 1 : "any"} value={spec.stop[key] ?? ""} onChange={(event) => update("stop", { ...spec.stop, [key]: event.target.value ? Number(event.target.value) : null })} /></label>
            ))}
          </div>
        </div>
      </div>

      <div className="campaign-card">
        <div className="campaign-toolbar">
          <h4>Numeric parameters</h4>
          <button type="button" style={theme.btn.secondary} onClick={addParameter}>Add parameter</button>
        </div>
        <div className="campaign-table-wrap">
          <table className="campaign-table">
            <thead><tr><th>Name</th><th>Minimum</th><th>Maximum</th><th>Step</th><th>Protocol bindings</th></tr></thead>
            <tbody>
              {spec.parameters.map((parameter, index) => (
                <tr key={`${parameter.name}-${index}`}>
                  <td><input aria-label={`Parameter ${index + 1} name`} value={parameter.name} onChange={(event) => update("parameters", spec.parameters.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} /></td>
                  {(["minimum", "maximum", "step"] as const).map((key) => (
                    <td key={key}><input aria-label={`Parameter ${index + 1} ${key}`} type="number" value={parameter[key]} onChange={(event) => update("parameters", spec.parameters.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: Number(event.target.value) } : item))} /></td>
                  ))}
                  <td>
                    <button type="button" aria-label={`Remove parameter ${index + 1}`} onClick={() => update("parameters", spec.parameters.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
                    <div className="campaign-bindings">
                      {numericChoices.map((choice) => (
                        <label key={bindingKey(choice)}><input type="checkbox" checked={parameter.bindings.some((binding) => bindingKey(binding) === bindingKey(choice))} onChange={(event) => update("parameters", spec.parameters.map((item, itemIndex) => itemIndex === index ? { ...item, bindings: event.target.checked ? [...item.bindings, { step_index: choice.step_index, argument: choice.argument }] : item.bindings.filter((binding) => bindingKey(binding) !== bindingKey(choice)) } : item))} />Step {choice.step_index + 1}: {choice.command}.{choice.argument}</label>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="campaign-card">
        <div className="campaign-toolbar">
          <h4>Initial design</h4>
          <span className="campaign-note">Samples in this order before model-selected formulations.</span>
          <button type="button" style={theme.btn.secondary} disabled={!spec.parameters.length || spec.optimizer.initial_points.length >= spec.optimizer.initial_trials} onClick={() => update("optimizer", { ...spec.optimizer, initial_points: [...spec.optimizer.initial_points, Object.fromEntries(spec.parameters.map((parameter) => [parameter.name, parameter.minimum]))] })}>Add design point</button>
        </div>
        {spec.optimizer.initial_points.length === 0 ? <p className="campaign-note">No fixed design points. Initial trials will be seeded random samples.</p> : (
          <div className="campaign-table-wrap"><table className="campaign-table"><thead><tr><th>Run</th>{spec.parameters.map((parameter) => <th key={parameter.name}>{parameter.name}</th>)}<th /></tr></thead><tbody>{spec.optimizer.initial_points.map((point, pointIndex) => <tr key={pointIndex}><td>{pointIndex + 1}</td>{spec.parameters.map((parameter) => <td key={parameter.name}><input aria-label={`Design ${pointIndex + 1} ${parameter.name}`} type="number" value={point[parameter.name] ?? parameter.minimum} onChange={(event) => update("optimizer", { ...spec.optimizer, initial_points: spec.optimizer.initial_points.map((item, itemIndex) => itemIndex === pointIndex ? { ...item, [parameter.name]: Number(event.target.value) } : item) })} /></td>)}<td><button type="button" aria-label={`Remove design point ${pointIndex + 1}`} onClick={() => update("optimizer", { ...spec.optimizer, initial_points: spec.optimizer.initial_points.filter((_, itemIndex) => itemIndex !== pointIndex) })}>Remove</button></td></tr>)}</tbody></table></div>
        )}
      </div>

      <div className="campaign-grid">
        <div className="campaign-card">
          <div className="campaign-toolbar"><h4>Sequence targets</h4><button type="button" style={theme.btn.secondary} onClick={() => update("sequences", [...spec.sequences, { name: `targets_${spec.sequences.length + 1}`, values: [], bindings: [] }])}>Add sequence</button></div>
          {spec.sequences.map((sequence, index) => (
            <div className="campaign-sequence" key={`${sequence.name}-${index}`}>
              <button type="button" aria-label={`Remove sequence ${index + 1}`} onClick={() => update("sequences", spec.sequences.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
              <input aria-label={`Sequence ${index + 1} name`} value={sequence.name} onChange={(event) => update("sequences", spec.sequences.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} />
              <textarea aria-label={`Sequence ${index + 1} values`} value={sequence.values.join(", ")} onChange={(event) => update("sequences", spec.sequences.map((item, itemIndex) => itemIndex === index ? { ...item, values: event.target.value.split(/[\n,]/).map((value) => value.trim()).filter(Boolean) } : item))} />
              <select aria-label={`Sequence ${index + 1} binding`} multiple value={sequence.bindings.map(bindingKey)} onChange={(event) => update("sequences", spec.sequences.map((item, itemIndex) => itemIndex === index ? { ...item, bindings: Array.from(event.target.selectedOptions, (option) => ({ step_index: Number(option.value.split(":")[0]), argument: option.value.split(":").slice(1).join(":") })).filter((binding) => binding.argument) } : item))}>
                {stringChoices.map((choice) => <option key={bindingKey(choice)} value={bindingKey(choice)}>Step {choice.step_index + 1}: {choice.command}.{choice.argument}</option>)}
              </select>
            </div>
          ))}
        </div>
        <div className="campaign-card">
          <h4>Mixture constraint</h4>
          <p className="campaign-note">Select component parameters whose values must sum to a fixed total.</p>
          <select aria-label="Sum constraint parameters" multiple value={spec.sum_constraint?.parameters ?? []} onChange={(event) => update("sum_constraint", { parameters: Array.from(event.target.selectedOptions, (option) => option.value), total: spec.sum_constraint?.total ?? 0 })}>{spec.parameters.map((parameter) => <option key={parameter.name} value={parameter.name}>{parameter.name}</option>)}</select>
          <input aria-label="Sum constraint total" type="number" value={spec.sum_constraint?.total ?? ""} onChange={(event) => update("sum_constraint", { parameters: spec.sum_constraint?.parameters ?? [], total: Number(event.target.value) })} />
          {spec.sum_constraint && <button type="button" onClick={() => update("sum_constraint", null)}>Clear constraint</button>}
        </div>
      </div>
        </div>
      </details>

      {validation.length > 0 && <div className="campaign-banner campaign-error" role="alert">{validation.map((issue) => <div key={issue}>{issue}</div>)}</div>}
      {error && <div className="campaign-banner campaign-error" role="alert">{error}</div>}
      </>}

      {activeSection === "history" && <div className="campaign-history-workspace">
        <div className="campaign-history-heading"><div><span>Saved campaign history</span><h4>Past and recoverable campaigns</h4></div><small>Opening a record does not change the current draft.</small></div>
        {loading && <span>Loading…</span>}
        {historyError && <div className="campaign-banner campaign-error" role="alert">Could not load campaign history: {historyError}</div>}
        {error && <div className="campaign-banner campaign-error" role="alert">{error}</div>}
        {!loading && !historyError && !records.length && <div className="campaign-empty-state"><strong>No saved campaigns yet</strong><span>Your current draft remains in Setup.</span></div>}
        {records.length > 0 && <select aria-label="Saved campaigns" value={selected ? String(selected.campaign_id) : ""} onChange={(event) => setSelected(records.find((record) => String(record.campaign_id) === event.target.value) ?? null)}>{records.map((record) => <option key={String(record.campaign_id)} value={String(record.campaign_id)}>#{record.campaign_id} · {record.spec.name} · {record.state}</option>)}</select>}
        {selected && (
          <>
            <div className="campaign-toolbar">
              <span className="campaign-success">{selected.state}</span>
              {selected.pause_requested && <span>Pause requested</span>}
              {selected.stop_requested && <span>Stop requested</span>}
              {selected.stop_reason && <span>{selected.stop_reason}</span>}
              {selected.error && <span>{selected.error}</span>}
            </div>
            <div className="campaign-results-grid">
              {bestTrace.length > 0 && <div className="campaign-chart" aria-label="Best objective trace">{bestTrace.map((value, index) => <div className="campaign-bar" key={index} title={`Trial ${index + 1}: ${value}`} style={{ height: `${Math.max(8, 100 * (value - Math.min(...bestTrace) + 0.001) / (Math.max(...bestTrace) - Math.min(...bestTrace) + 0.001))}%` }} />)}</div>}
              <TernaryPlot record={selected} />
            </div>
            <ColorReadout record={selected} />
            <div className="campaign-table-wrap"><table className="campaign-table"><thead><tr><th>Sample</th><th>Batch</th><th>Well / parameters</th><th>Objective</th><th>Result path</th><th>Status</th><th>Native run</th></tr></thead><tbody>{selected.trials.map((trial) => <tr key={trial.index}><td>{trial.index + 1}</td><td>{trial.batch_index ?? Math.floor(trial.index / (selected.spec.batch_size || 1)) + 1}</td><td><strong>{trial.sample_well ?? "—"}</strong><br />{Object.entries(trial.parameters).map(([key, value]) => `${key}=${value}`).join(", ")}</td><td>{trial.objective ?? "—"}</td><td><code>{trial.objective_path ?? selected.spec.objective.path}</code></td><td>{trial.objective_status ?? trial.state}</td><td><button type="button" onClick={() => onRunSelected?.(trial.run_id)}>Open run {trial.run_id}</button></td></tr>)}</tbody></table></div>
            {["failed", "interrupted", "stopped"].includes(selected.state) && <details className="campaign-history-recovery"><summary>Recovery and fluid-state attachment</summary><CampaignFluidState deckFile={deckFile} deck={deck} states={availableFluidStates} selectedId={spec.fluid_state_id} onSelect={(id) => update("fluid_state_id", id)} selectedCampaign={selected} onCampaignAttached={(record) => { setSelected(record); setRecords((current) => current.map((item) => String(item.campaign_id) === String(record.campaign_id) ? record : item)); }} suggestedContainers={[redSource, yellowSource, blueSource]} /></details>}
            {selected.state === "awaiting_observation" && <div className="campaign-actions"><input aria-label="Manual observation" type="number" value={observation} onChange={(event) => setObservation(event.target.value)} /><button type="button" onClick={async () => { try { setSelected(await campaignApi.observation(selected.campaign_id, Number(observation))); setObservation(""); } catch (caught) { setError(campaignErrorMessage(caught)); } }}>Submit observation</button></div>}
            <div className="campaign-actions">
              {["failed", "interrupted"].includes(selected.state) && selected.trials.at(-1)?.state === "succeeded" && <button type="button" onClick={() => void control("resume")}>Resume campaign</button>}
              {!TERMINAL.has(selected.state) && <button type="button" onClick={() => { setSelected(selected); setActiveSection("run"); }}>View live run</button>}
            </div>
          </>
        )}
      </div>}
    </section>
  );
}
