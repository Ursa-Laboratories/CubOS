import { useMemo, useState } from "react";
import { campaignApi } from "./api";
import type { NormalizedPoint } from "../gantry/cameraGeometry";

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValues(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

interface Props {
  runId: string;
  expectedWell: string;
  measurement: Record<string, unknown>;
  selectedCenter: NormalizedPoint | null;
  onSelectedCenter: (point: NormalizedPoint) => void;
  onMeasurement: (measurement: Record<string, unknown>) => void;
}

export default function ColorTargetReview({ runId, expectedWell, measurement, selectedCenter, onSelectedCenter, onMeasurement }: Props) {
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

  const selectPoint = (event: React.MouseEvent<HTMLImageElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    onSelectedCenter({
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    });
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

  return (
    <div className="campaign-target-review" aria-label="Target image review">
      <div className="campaign-toolbar">
        <div>
          <h4>Review saved target frame</h4>
          <p className="campaign-note">This is the exact saved frame from run {runId}. Click the physical {expectedWell} center, then analyze this same image again. No recapture or motion occurs.</p>
        </div>
        <span className={status === "accepted" ? "campaign-success" : "campaign-camera-stale"}>{status}</span>
      </div>
      <div className="campaign-target-review-grid">
        <div className="campaign-target-image">
          {!rawImageError && <img src={campaignApi.colorTargetImageUrl(runId)} alt={`Saved target frame for ${expectedWell}`} onClick={selectPoint} onError={() => setRawImageError(true)} />}
          {rawImageError && <div className="campaign-target-image-error">Saved frame unavailable. Capture a new target; older target runs may predate immutable image storage.</div>}
          {selectedCenter && <span className="campaign-selected-center" style={{ left: `${selectedCenter.x * 100}%`, top: `${selectedCenter.y * 100}%` }} />}
        </div>
        <div>
          {!analysisImageError && <img className="campaign-analysis-image" src={campaignApi.colorTargetAnalysisImageUrl(runId, revision)} alt="Color analysis diagnostics" onError={() => setAnalysisImageError(true)} />}
          {analysisImageError && <div className="campaign-target-image-error">Annotated diagnostics are unavailable for this analysis revision.</div>}
          <div className="campaign-color-evidence">
            <span><strong>Expected well</strong> {expectedWell} · operator selection required</span>
            <span><strong>Detected center</strong> {numberValue(roi?.center_x_px)?.toFixed(1) ?? "—"}, {numberValue(roi?.center_y_px)?.toFixed(1) ?? "—"} px</span>
            <span><strong>Residual</strong> {numberValue(roi?.center_residual_px)?.toFixed(1) ?? "—"} px</span>
            <span><strong>Valid ROI</strong> {numberValue(quality?.valid_fraction) === null ? "—" : `${(numberValue(quality?.valid_fraction)! * 100).toFixed(1)}%`}</span>
            <span><strong>Glare</strong> {numberValue(quality?.glare_fraction) === null ? "—" : `${(numberValue(quality?.glare_fraction)! * 100).toFixed(1)}%`}</span>
            <span><strong>Color calibration</strong> {typeof profile?.calibration_status === "string" ? profile.calibration_status : "not reported"}</span>
          </div>
        </div>
      </div>
      <div className="campaign-actions">
        {selectedCenter && <span className="campaign-note">Selected x {selectedCenter.x.toFixed(3)}, y {selectedCenter.y.toFixed(3)} normalized</span>}
        <button type="button" onClick={() => void reanalyze()} disabled={!selectedCenter || busy || rawImageError}>{busy ? "Analyzing saved frame…" : "Analyze saved frame at selected center"}</button>
      </div>
      {flags.length > 0 && <div className="campaign-banner campaign-error" role="alert">{flags.join(" · ")}</div>}
      {error && <div className="campaign-banner campaign-error" role="alert">{error}</div>}
      <p className="campaign-note">The selection identifies the intended image region for analysis. It does not save a physical offset, move the gantry, or make computer vision proof of well identity.</p>
    </div>
  );
}
