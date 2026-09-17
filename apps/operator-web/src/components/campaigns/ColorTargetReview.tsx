import { useMemo, useState } from "react";
import { campaignApi } from "./api";
import type { NormalizedPoint } from "../gantry/cameraGeometry";
import "./ColorTargetReview.css";

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValues(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

const FLAG_LABELS: Record<string, string> = {
  expected_center_unverified: "The expected well has not been selected",
  well_not_found: "No clear well edge near the selected point",
  low_detection_confidence: "Well edge is uncertain",
  ambiguous_well_detection: "More than one possible well was found",
  insufficient_valid_pixels: "Too few usable pixels",
  low_valid_fraction: "Too much of the sample area was excluded",
  excessive_low_clipping: "Dark pixels are clipped",
  excessive_high_clipping: "Bright pixels are clipped",
  excessive_glare: "Glare covers too much of the sample",
  underexposed: "The saved frame is too dark",
  overexposed: "The saved frame is too bright",
  capture_profile_unverified: "Camera settings were not recorded",
  capture_profile_changed_during_acquisition: "Camera settings changed during capture",
};

const CAPTURE_FLAGS = [
  "capture_profile_unverified",
  "capture_profile_changed_during_acquisition",
  "underexposed",
  "overexposed",
  "excessive_low_clipping",
  "excessive_high_clipping",
  "excessive_glare",
];

interface Props {
  runId: string;
  expectedWell: string;
  measurement: Record<string, unknown>;
  selectedCenter: NormalizedPoint | null;
  selectionNeedsAnalysis?: boolean;
  onSelectedCenter: (point: NormalizedPoint) => void;
  onMeasurement: (measurement: Record<string, unknown>) => void;
}

function reviewGuidance(status: string, flags: string[], expectedWell: string, selectionNeedsAnalysis: boolean) {
  if (selectionNeedsAnalysis) {
    return {
      tone: "select",
      badge: "Reanalysis required",
      title: "Selection changed — reanalyze this region",
      detail: "Use the selected center to refresh the target.",
    };
  }
  if (status === "accepted") {
    return {
      tone: "ready",
      badge: "Ready",
      title: "This saved frame passed the current image checks",
      detail: "This target is ready to use.",
    };
  }
  const captureProblem = CAPTURE_FLAGS.find((flag) => flags.includes(flag));
  if (captureProblem) {
    return {
      tone: "capture",
      badge: "New capture needed",
      title: FLAG_LABELS[captureProblem] ?? "The saved frame has an image-quality problem",
      detail: "Capture a new target after fixing the image quality.",
    };
  }
  if (flags.includes("expected_center_unverified")) {
    return {
      tone: "select",
      badge: "Select the well",
      title: `Select the center of ${expectedWell}`,
      detail: "Click the center, then use target.",
    };
  }
  if (flags.some((flag) => [
    "well_not_found",
    "low_detection_confidence",
    "ambiguous_well_detection",
    "insufficient_valid_pixels",
    "low_valid_fraction",
  ].includes(flag))) {
    return {
      tone: "select",
      badge: "Check the well",
      title: `The analysis could not isolate ${expectedWell} confidently`,
      detail: "Select the center and use target, or capture again.",
    };
  }
  return {
    tone: "review",
    badge: "Review needed",
    title: "This saved frame did not pass the image checks",
    detail: "Open Details for diagnostics, or capture again.",
  };
}

export default function ColorTargetReview({ runId, expectedWell, measurement, selectedCenter, selectionNeedsAnalysis = false, onSelectedCenter, onMeasurement }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rawImageError, setRawImageError] = useState(false);
  const [analysisImageError, setAnalysisImageError] = useState(false);
  const roi = objectValue(measurement.roi);
  const quality = objectValue(measurement.quality);
  const profile = objectValue(measurement.processing_profile);
  const revision = numberValue(measurement.analysis_revision) ?? 0;
  const flags = useMemo(() => stringValues(quality?.flags), [quality]);
  const status = typeof measurement.measurement_status === "string" ? measurement.measurement_status : "rejected";
  const guidance = useMemo(
    () => reviewGuidance(status, flags, expectedWell, selectionNeedsAnalysis),
    [status, flags, expectedWell, selectionNeedsAnalysis],
  );

  const setCenter = (x: number, y: number) => onSelectedCenter({
    x: Math.max(0, Math.min(1, x)),
    y: Math.max(0, Math.min(1, y)),
  });

  const selectPoint = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (event.detail === 0) {
      if (!selectedCenter) setCenter(0.5, 0.5);
      return;
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    setCenter(
      (event.clientX - bounds.left) / bounds.width,
      (event.clientY - bounds.top) / bounds.height,
    );
  };

  const moveSelection = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const step = event.shiftKey ? 0.05 : 0.01;
    const current = selectedCenter ?? { x: 0.5, y: 0.5 };
    const movement: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, -step],
      ArrowDown: [0, step],
    };
    if (event.key === "Home") {
      event.preventDefault();
      event.stopPropagation();
      setCenter(0.5, 0.5);
      return;
    }
    const delta = movement[event.key];
    if (!delta) return;
    event.preventDefault();
    event.stopPropagation();
    setCenter(current.x + delta[0], current.y + delta[1]);
  };

  const stopSelectionKeyUp = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home"].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
  };

  const reanalyze = async () => {
    if (!selectedCenter) return;
    setBusy(true);
    setError(null);
    try {
      const next = await campaignApi.reanalyzeColorTarget(runId, [selectedCenter.x, selectedCenter.y]);
      setAnalysisImageError(false);
      onMeasurement(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const validFraction = numberValue(quality?.valid_fraction);
  const glareFraction = numberValue(quality?.glare_fraction);
  const calibrationStatus = typeof profile?.calibration_status === "string"
    ? profile.calibration_status.replaceAll("_", " ")
    : "not reported";

  return (
    <section className="target-review" aria-labelledby="target-review-title">
      <header className="target-review__header">
        <div>
          <p className="target-review__kicker">Saved target · revision {revision}</p>
          <h4 id="target-review-title">Select well center</h4>
          <p>Click the center of {expectedWell}, then use it as the target.</p>
        </div>
        <span className={`target-review__status target-review__status--${guidance.tone}`}>{guidance.badge}</span>
      </header>

      <div className={`target-review__guidance target-review__guidance--${guidance.tone}`}>
        <strong>{guidance.title}</strong>
        <p>{guidance.detail}</p>
      </div>

      <div className="target-review__frame-wrap">
        {!rawImageError ? (
          <button
            type="button"
            className="target-review__frame"
            onClick={selectPoint}
            onKeyDown={moveSelection}
            onKeyUp={stopSelectionKeyUp}
            aria-label={`Select the center of ${expectedWell}. Use arrow keys for fine adjustment and Shift plus arrow keys for larger steps.`}
          >
            <img
              src={campaignApi.colorTargetImageUrl(runId)}
              alt={`Saved camera frame containing the intended ${expectedWell} target`}
              onError={() => setRawImageError(true)}
            />
            {selectedCenter && (
              <span
                className="target-review__selected-center"
                style={{ left: `${selectedCenter.x * 100}%`, top: `${selectedCenter.y * 100}%` }}
                aria-hidden="true"
              />
            )}
          </button>
        ) : (
          <div className="target-review__image-error">Saved frame unavailable. Capture a new target; older runs may predate immutable image storage.</div>
        )}
        <div className="target-review__frame-help">
        <span>Click the center of {expectedWell}.</span>
        </div>
      </div>

      <div className="target-review__action-row">
        <div>
          <span className="target-review__action-label">Operator-selected center</span>
          <strong>{selectedCenter ? `${selectedCenter.x.toFixed(3)}, ${selectedCenter.y.toFixed(3)} normalized` : "Not selected"}</strong>
        </div>
        <button type="button" onClick={() => void reanalyze()} disabled={!selectedCenter || busy || rawImageError}>
          {busy ? "Using target…" : "Use target"}
        </button>
      </div>

      {error && <div className="campaign-banner campaign-error" role="alert">{error}</div>}

      <details className="target-review__diagnostics">
        <summary>View analysis overlay and measurements</summary>
        <div className="target-review__diagnostic-grid">
          <div>
            {!analysisImageError ? (
              <img
                src={campaignApi.colorTargetAnalysisImageUrl(runId, revision)}
                alt={`Analysis overlay for ${expectedWell}, revision ${revision}`}
                onError={() => setAnalysisImageError(true)}
              />
            ) : (
              <div className="target-review__image-error">The annotated overlay is unavailable for this revision.</div>
            )}
            <div className="target-review__legend" aria-label="Analysis overlay legend">
              <span><i className="target-review__swatch target-review__swatch--expected" />Expected point</span>
              <span><i className="target-review__swatch target-review__swatch--candidate" />Candidate well edge</span>
              <span><i className="target-review__swatch target-review__swatch--rejected" />Rejected selection or pixels</span>
              <span><i className="target-review__swatch target-review__swatch--accepted" />Accepted selection</span>
            </div>
          </div>
          <div className="target-review__evidence">
            <div><span>Expected well</span><strong>{expectedWell}</strong><small>Named by the protocol; computer vision does not verify identity.</small></div>
            <div><span>Detected center</span><strong>{numberValue(roi?.center_x_px)?.toFixed(1) ?? "—"}, {numberValue(roi?.center_y_px)?.toFixed(1) ?? "—"} px</strong></div>
            <div><span>Center residual</span><strong>{numberValue(roi?.center_residual_px)?.toFixed(1) ?? "—"} px</strong></div>
            <div><span>Usable sample pixels</span><strong>{validFraction === null ? "—" : `${(validFraction * 100).toFixed(1)}%`}</strong></div>
            <div><span>Glare</span><strong>{glareFraction === null ? "—" : `${(glareFraction * 100).toFixed(1)}%`}</strong></div>
            <div><span>Camera color estimate</span><strong>{calibrationStatus}</strong><small>No claim of traceable optical color calibration.</small></div>
          </div>
        </div>
        {flags.length > 0 && (
          <div className="target-review__flags">
            <strong>Why this revision was rejected</strong>
            <ul>{flags.map((flag) => <li key={flag}>{FLAG_LABELS[flag] ?? flag.replaceAll("_", " ")}</li>)}</ul>
          </div>
        )}
      </details>

      <p className="target-review__boundary">The selected point identifies an image region only. It does not save a physical offset or establish the well’s identity.</p>
    </section>
  );
}
