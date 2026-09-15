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
  CampaignRecord,
  CampaignSpec,
  ColorTargetRun,
  ProtocolStep,
} from "./types";
import "./CampaignPanel.css";
import type { NormalizedPoint } from "../gantry/cameraGeometry";

const EDITOR_KEY = "cubos.active-learning.campaign-editor";
const TARGET_REVIEW_KEY = "cubos.active-learning.target-review";
const TERMINAL = new Set(["completed", "stopped", "failed", "interrupted"]);

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
  const [spec, setSpec] = useState<CampaignSpec>(() => restoredSpec(props));
  const files = useRef({ gantryFile, deckFile, protocolFile });
  const [records, setRecords] = useState<CampaignRecord[]>([]);
  const [selected, setSelected] = useState<CampaignRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<string[]>([]);
  const [observation, setObservation] = useState("");
  const [validated, setValidated] = useState(false);
  const [presetIssues, setPresetIssues] = useState<string[]>([]);
  const [targetWell, setTargetWell] = useState(restoredReview?.targetWell ?? "plate.A1");
  const [redSource, setRedSource] = useState("stocks.A1");
  const [yellowSource, setYellowSource] = useState("stocks.A2");
  const [blueSource, setBlueSource] = useState("stocks.A3");
  const [candidateText, setCandidateText] = useState(CANDIDATE_WELLS.join(", "));
  const [cameraInstrument, setCameraInstrument] = useState(restoredReview?.cameraInstrument ?? "camera");
  const [roiFraction, setRoiFraction] = useState(restoredReview?.roiFraction ?? 0.5);
  const [captureImageHeight, setCaptureImageHeight] = useState(restoredReview?.captureImageHeight ?? "");
  const [targetLab, setTargetLab] = useState<number[] | null>(() => restoredReview?.measurement.measurement_status === "accepted" ? numericTriplet(restoredReview.measurement.lab) : null);
  const [targetRunId, setTargetRunId] = useState<string | null>(restoredReview?.runId ?? null);
  const [targetMeasurement, setTargetMeasurement] = useState<Record<string, unknown> | null>(restoredReview?.measurement ?? null);
  const [targetExpectedCenter, setTargetExpectedCenter] = useState<NormalizedPoint | null>(restoredReview?.selectedCenter ?? null);
  const visibleTargetLab = targetLab ?? (protocolTargetProfileId ? protocolTargetLab : null);
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

  useEffect(() => localStorage.setItem(EDITOR_KEY, JSON.stringify(spec)), [spec]);
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
    } satisfies TargetReviewDraft));
  }, [targetRunId, targetMeasurement, targetExpectedCenter, targetWell, cameraInstrument, roiFraction, captureImageHeight]);
  useEffect(() => {
    if (
      files.current.gantryFile !== gantryFile
      || files.current.deckFile !== deckFile
      || files.current.protocolFile !== protocolFile
    ) {
      files.current = { gantryFile, deckFile, protocolFile };
      setSpec((current) => ({
        ...current,
        gantry_file: gantryFile ?? current.gantry_file,
        deck_file: deckFile ?? current.deck_file,
        protocol_file: protocolFile ?? current.protocol_file,
      }));
    }
  }, [gantryFile, deckFile, protocolFile]);

  const refresh = useCallback(async () => {
    try {
      const next = await campaignApi.list();
      setRecords(next);
      setSelected((current) => current
        ? next.find((record) => String(record.campaign_id) === String(current.campaign_id)) ?? current
        : next[0] ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
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
    return issues;
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
      setError(caught instanceof Error ? caught.message : String(caught));
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
      setSelected(record);
      setRecords((current) => [record, ...current]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };
  const control = async (action: "pause" | "resume" | "stop" | "cancel") => {
    if (!selected) return;
    setBusy(true);
    try {
      setSelected(await campaignApi[action](selected.campaign_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };
  const applyColorPreset = () => {
    const preset = colorMatchingSpec(spec, protocolSteps);
    setSpec(preset.spec);
    setPresetIssues(preset.issues);
    setValidation([]);
    setValidated(false);
  };
  const readTargetAndPrepare = async () => {
    if (!gantryFile || !deckFile) {
      setError("Select the station gantry and deck before reading the target.");
      return;
    }
    const imageHeight = captureImageHeight.trim() === "" ? null : Number(captureImageHeight);
    if (imageHeight !== null && !Number.isFinite(imageHeight)) {
      setError("Capture image height must be a finite labware-relative offset in mm.");
      return;
    }
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
      const message = caught instanceof Error ? caught.message : String(caught);
      setTargetError(message);
      setTargetStatus(submittedRun ? `Could not refresh target run ${submittedRun.run_id}.` : "Target request was rejected before a run was created.");
    } finally {
      setTargetBusy(false);
    }
  };

  const buildFromAcceptedTarget = async () => {
    if (!gantryFile || !deckFile || !targetRunId || !targetMeasurement || !targetExpectedCenter) return;
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
      setSpec(prepared);
      setPresetIssues([]);
      setValidation([]);
      setValidated(false);
      setTargetStatus(`Target read from ${targetWell}. Campaign protocol ${prepared.protocol_file} is ready to validate.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
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

  return (
    <section className="campaign-panel" style={theme.card} aria-label="Active learning campaigns">
      <div className="campaign-header">
        <div>
          <h3 className="campaign-title">Active learning & DOE</h3>
          <div className="campaign-subtitle">Design, execute, measure, and learn through native CubOS runs.</div>
        </div>
        <div className="campaign-actions">
          <button type="button" style={theme.btn.secondary} onClick={() => void validate()} disabled={busy}>Validate</button>
          {validated && <span className="campaign-success">Validated</span>}
          <button type="button" style={theme.btn.primary} onClick={() => void start()} disabled={busy || !!disabledReason}>Start campaign</button>
        </div>
      </div>
      {disabledReason && <div className="campaign-banner campaign-info">{disabledReason}</div>}
      {selected && (
        <div className="campaign-monitor" role="status">
          <strong>{selected.state.replaceAll("_", " ")}</strong>
          <span>{selected.trials.length} / {selected.spec.stop.max_trials} trials · best {selected.best_objective ?? "—"}</span>
          {selected.stop_reason && <span>{selected.stop_reason.replaceAll("_", " ")}</span>}
          {selected.active_run_id && <button type="button" onClick={() => onRunSelected?.(selected.active_run_id!)}>View current trial</button>}
        </div>
      )}
      {selected?.state === "running" && !selected.spec.mock_mode && campaignCameraInstrument && (
        <CampaignCameraMonitor instrument={campaignCameraInstrument} />
      )}
      {selected?.state === "running" && !selected.spec.mock_mode && !campaignCameraInstrument && (
        <div className="campaign-banner campaign-info">Load the running campaign&apos;s gantry and protocol to identify its camera before opening the live monitor.</div>
      )}

      <div className="campaign-card campaign-color-setup">
        <div className="campaign-toolbar">
          <div>
            <h4>Color matching setup</h4>
            <p className="campaign-note">Choose the existing target and three dye stocks here. Capture and review the target before building the candidate protocol and campaign draft.</p>
          </div>
          <button type="button" style={theme.btn.secondary} onClick={applyColorPreset}>Use loaded protocol</button>
        </div>
        <div className="campaign-fields campaign-color-fields">
          <label className="campaign-field">Target well<select aria-label="Target well" value={targetWell} onChange={(event) => { setTargetWell(event.target.value); setTargetRunId(null); setTargetMeasurement(null); setTargetExpectedCenter(null); }}>{PLATE_WELLS.map((well) => <option key={well}>{well}</option>)}</select></label>
          <label className="campaign-field">Red stock<input aria-label="Red stock" value={redSource} onChange={(event) => setRedSource(event.target.value)} /></label>
          <label className="campaign-field">Yellow stock<input aria-label="Yellow stock" value={yellowSource} onChange={(event) => setYellowSource(event.target.value)} /></label>
          <label className="campaign-field">Blue stock<input aria-label="Blue stock" value={blueSource} onChange={(event) => setBlueSource(event.target.value)} /></label>
          <label className="campaign-field">Camera<input aria-label="Color camera" value={cameraInstrument} onChange={(event) => { setCameraInstrument(event.target.value); setTargetRunId(null); setTargetMeasurement(null); setTargetExpectedCenter(null); }} /></label>
          <label className="campaign-field">Sample radius / detected well radius<input aria-label="Color ROI fraction" type="number" min="0.1" max="1" step="0.05" value={roiFraction} onChange={(event) => { setRoiFraction(Number(event.target.value)); setTargetRunId(null); setTargetMeasurement(null); setTargetExpectedCenter(null); }} /></label>
          <label className="campaign-field">Capture height relative to well (mm)<input aria-label="Color capture image height" type="number" step="0.5" value={captureImageHeight} onChange={(event) => { setCaptureImageHeight(event.target.value); setTargetRunId(null); setTargetMeasurement(null); setTargetExpectedCenter(null); }} placeholder="Use configured ceiling" /></label>
          <label className="campaign-field campaign-candidate-field">Candidate wells<textarea aria-label="Color candidate wells" value={candidateText} onChange={(event) => setCandidateText(event.target.value)} /></label>
        </div>
        <p className="campaign-note">Capture height is relative to the calibrated well surface: positive is above it and negative is below. Blank preserves the existing configured ceiling. CubOS validates the selected height against the calibrated labware, working volume, and collision plan, then retracts to the configured planning ceiling.</p>
        {captureCarriageZ !== null && <p className="campaign-note">Preview: {targetWell} surface Z {targetWellZ?.toFixed(3)} mm + image height {numericCaptureHeight?.toFixed(3)} mm + camera depth {cameraDepth?.toFixed(3)} mm = carriage Z {captureCarriageZ.toFixed(3)} mm. Review physical camera clearance before running.</p>}
        <p className="campaign-note">After capture, select the intended well center on the saved image. Computer vision may locate a well-like circle near it, but cannot verify the well identity.</p>
        <div className="campaign-color-limits">50–200 µL per dye · 300 µL total · 5 µL grid · six simplex starts · ΔE00 target ≤ 3</div>
        <div className="campaign-actions">
          <button type="button" style={theme.btn.primary} onClick={() => void readTargetAndPrepare()} disabled={targetBusy || !!disabledReason}>{targetBusy ? "Capturing target…" : `Capture ${targetWell} target for review`}</button>
          {visibleTargetLab && <span className="campaign-target-chip"><span className="campaign-swatch" style={{ backgroundColor: `lab(${visibleTargetLab[0]}% ${visibleTargetLab[1]} ${visibleTargetLab[2]})` }} />Target Lab {visibleTargetLab.map((value) => value.toFixed(4)).join(", ")}</span>}
          {visibleTargetLab && protocolFile && <span className="campaign-note">Accepted target will be saved in {protocolFile} with its processing profile.</span>}
          {!visibleTargetLab && protocolTargetLab && <span className="campaign-note">The loaded protocol contains a legacy reference Lab without accepted processing-profile provenance. Capture a new target before use.</span>}
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
        <ColorTargetReview
          key={targetRunId}
          runId={targetRunId}
          expectedWell={targetWell}
          measurement={targetMeasurement}
          selectedCenter={targetExpectedCenter}
          onSelectedCenter={setTargetExpectedCenter}
          onMeasurement={(measurement) => {
            setTargetMeasurement(measurement);
            const lab = numericTriplet(measurement.lab);
            setTargetLab(measurement.measurement_status === "accepted" ? lab : null);
            setTargetStatus(measurement.measurement_status === "accepted"
              ? "Saved target frame passed quality review. Build the campaign when the physical setup is ready."
              : "Saved target frame remains rejected. Review the diagnostics, adjust the selected center, and analyze the same frame again.");
          }}
        />
      )}
      {targetRunId && targetMeasurement?.measurement_status === "accepted" && (
        <div className="campaign-actions">
          <button type="button" style={theme.btn.primary} onClick={() => void buildFromAcceptedTarget()} disabled={targetBusy || !targetExpectedCenter || (!spec.mock_mode && spec.fluid_state_id === null)}>Build campaign from accepted target</button>
          {!spec.mock_mode && spec.fluid_state_id === null && <span className="campaign-note">Create or select a reconciled fluid state before building a real color campaign.</span>}
        </div>
      )}
      {presetIssues.length > 0 && (
        <div className="campaign-banner campaign-info">
          {presetIssues.map((issue) => <div key={issue}>{issue}</div>)}
        </div>
      )}

      <div className="campaign-grid">
        <div className="campaign-card">
          <h4>Experiment</h4>
          <div className="campaign-fields">
            <label className="campaign-field">Name<input aria-label="Campaign name" value={spec.name} onChange={(event) => update("name", event.target.value)} /></label>
            <label className="campaign-field">Mode<select aria-label="Execution mode" value={spec.mock_mode ? "mock" : "real"} onChange={(event) => update("mock_mode", event.target.value === "mock")}><option value="mock">Offline mock (safe)</option><option value="real">Real hardware</option></select></label>
            <label className="campaign-field">Objective path<input aria-label="Objective result path" value={spec.objective.path} onChange={(event) => update("objective", { ...spec.objective, path: event.target.value })} placeholder="results.0.value" /></label>
            <label className="campaign-field">Direction<select aria-label="Objective direction" value={spec.objective.direction} onChange={(event) => update("objective", { ...spec.objective, direction: event.target.value as "minimize" | "maximize" })}><option value="minimize">Minimize</option><option value="maximize">Maximize</option></select></label>
            <label className="campaign-field">Objective type<select aria-label="Objective mode" value={spec.objective.mode} onChange={(event) => update("objective", { ...spec.objective, mode: event.target.value as "result" | "manual" })}><option value="result">Protocol result</option><option value="manual">Manual observation</option></select></label>
          </div>
        </div>
        <CampaignFluidState
          deckFile={deckFile}
          deck={deck}
          states={availableFluidStates}
          selectedId={spec.fluid_state_id}
          onSelect={(id) => update("fluid_state_id", id)}
          selectedCampaign={selected}
          onCampaignAttached={(record) => {
            setSelected(record);
            setRecords((current) => current.map((item) => String(item.campaign_id) === String(record.campaign_id) ? record : item));
          }}
          suggestedContainers={[redSource, yellowSource, blueSource]}
        />
        <div className="campaign-card">
          <h4>Learning strategy</h4>
          <div className="campaign-fields">
            <label className="campaign-field">Acquisition<select aria-label="Optimizer method" value={spec.optimizer.method} onChange={(event) => update("optimizer", { ...spec.optimizer, method: event.target.value as "ei" | "lcb" | "random" })}><option value="ei">Expected improvement</option><option value="lcb">Lower confidence bound</option><option value="random">Random / DOE only</option></select></label>
            <label className="campaign-field">GP kernel<select aria-label="GP kernel" value={spec.optimizer.kernel} onChange={(event) => update("optimizer", { ...spec.optimizer, kernel: event.target.value as "matern52" | "rbf" })}><option value="matern52">Matérn 5/2</option><option value="rbf">RBF</option></select></label>
            <label className="campaign-field">Initial trials<input aria-label="Initial trials" type="number" value={spec.optimizer.initial_trials} onChange={(event) => update("optimizer", { ...spec.optimizer, initial_trials: Number(event.target.value) })} /></label>
            <label className="campaign-field">Exploration<input aria-label="Exploration" type="number" value={spec.optimizer.exploration} onChange={(event) => update("optimizer", { ...spec.optimizer, exploration: Number(event.target.value) })} /></label>
            <label className="campaign-field">Seed<input aria-label="Optimizer seed" type="number" value={spec.optimizer.seed} onChange={(event) => update("optimizer", { ...spec.optimizer, seed: Number(event.target.value) })} /></label>
          </div>
        </div>
        <div className="campaign-card">
          <h4>Stop limits</h4>
          <p className="campaign-note">Limits are checked between trials. Cancel interrupts the active native run.</p>
          <div className="campaign-fields">
            {(["max_trials", "patience", "min_improvement", "max_seconds", "target_value"] as const).map((key) => (
              <label className="campaign-field" key={key}>{key.replaceAll("_", " ")}<input aria-label={key.replaceAll("_", " ")} type="number" value={spec.stop[key] ?? ""} onChange={(event) => update("stop", { ...spec.stop, [key]: event.target.value ? Number(event.target.value) : null })} /></label>
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
          <span className="campaign-note">Runs in this order before model-selected trials.</span>
          <button type="button" style={theme.btn.secondary} onClick={() => update("optimizer", { ...spec.optimizer, initial_points: [...spec.optimizer.initial_points, Object.fromEntries(spec.parameters.map((parameter) => [parameter.name, parameter.minimum]))] })}>Add design point</button>
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

      {validation.length > 0 && <div className="campaign-banner campaign-error" role="alert">{validation.map((issue) => <div key={issue}>{issue}</div>)}</div>}
      {error && <div className="campaign-banner campaign-error">{error}</div>}

      <div className="campaign-card">
        <h4>Campaign history</h4>
        {loading && <span>Loading…</span>}
        {!loading && !records.length && <div className="campaign-note">No campaigns yet. The draft is saved locally.</div>}
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
            <div className="campaign-table-wrap"><table className="campaign-table"><thead><tr><th>Trial</th><th>Parameters</th><th>Objective</th><th>Status</th><th>Run</th></tr></thead><tbody>{selected.trials.map((trial) => <tr key={trial.index}><td>{trial.index + 1}</td><td>{Object.entries(trial.parameters).map(([key, value]) => `${key}=${value}`).join(", ")}</td><td>{trial.objective ?? "—"}</td><td>{trial.state}</td><td><button type="button" onClick={() => onRunSelected?.(trial.run_id)}>Open run</button></td></tr>)}</tbody></table></div>
            {selected.state === "awaiting_observation" && <div className="campaign-actions"><input aria-label="Manual observation" type="number" value={observation} onChange={(event) => setObservation(event.target.value)} /><button type="button" onClick={async () => { try { setSelected(await campaignApi.observation(selected.campaign_id, Number(observation))); setObservation(""); } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); } }}>Submit observation</button></div>}
            <div className="campaign-actions">
              {["failed", "interrupted"].includes(selected.state) && selected.trials.at(-1)?.state === "succeeded" && <button type="button" onClick={() => void control("resume")}>Resume campaign</button>}
              {selected.state === "paused" && <button type="button" onClick={() => void control("resume")}>Resume</button>}
              {selected.state === "running" && <button type="button" onClick={() => void control("pause")}>Pause after trial</button>}
              {!TERMINAL.has(selected.state) && <><button type="button" onClick={() => void control("stop")}>Stop after trial</button><button type="button" onClick={() => void control("cancel")}>Cancel run</button></>}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
