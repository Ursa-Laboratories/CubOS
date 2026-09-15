import { useEffect, useState } from "react";
import { cameraMonitorApi } from "./api";
import type { CameraMonitorStatus } from "./types";

const POLL_MS = 800;
const STALE_AFTER_SECONDS = 3;

function numberField(source: Record<string, unknown> | null, key: string): number | null {
  const value = source?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textList(source: Record<string, unknown> | null, key: string): string[] {
  const value = source?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

export default function CampaignCameraMonitor({ instrument }: { instrument: string }) {
  const [status, setStatus] = useState<CameraMonitorStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<{ frameId: number | null; confirmed: boolean; note: string }>({ frameId: null, confirmed: false, note: "" });

  useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
    let acquireTimer: ReturnType<typeof setTimeout> | null = null;
    let leaseId: string | null = null;
    let acquiring = false;

    const poll = async () => {
      try {
        const next = await cameraMonitorApi.get(instrument);
        if (cancelled) return;
        setStatus(next);
        setError(next.error);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : String(caught));
      }
      if (!cancelled) pollTimer = setTimeout(() => void poll(), POLL_MS);
    };

    const heartbeat = async () => {
      if (!leaseId || cancelled) return;
      try {
        const next = await cameraMonitorApi.heartbeat(instrument, leaseId);
        if (!cancelled) {
          setStatus(next);
          setError(next.error);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(`Camera monitor heartbeat: ${caught instanceof Error ? caught.message : String(caught)}. Reacquiring preview lease…`);
          leaseId = null;
          void acquire();
        }
        return;
      }
      if (!cancelled) heartbeatTimer = setTimeout(() => void heartbeat(), 5000);
    };

    async function acquire() {
      if (cancelled || acquiring || leaseId) return;
      acquiring = true;
      try {
        const next = await cameraMonitorApi.start(instrument);
        if (cancelled) {
          if (next.lease_id) void cameraMonitorApi.stop(instrument, next.lease_id).catch(() => undefined);
          return;
        }
        if (!next.lease_id) throw new Error("Camera monitor did not return a lease.");
        leaseId = next.lease_id;
        setStatus(next);
        setError(next.error);
        heartbeatTimer = setTimeout(() => void heartbeat(), 5000);
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : String(caught));
          acquireTimer = setTimeout(() => void acquire(), 1000);
        }
      } finally {
        acquiring = false;
      }
    }

    void acquire();
    void poll();

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
      if (heartbeatTimer) clearTimeout(heartbeatTimer);
      if (acquireTimer) clearTimeout(acquireTimer);
      if (leaseId) void cameraMonitorApi.stop(instrument, leaseId).catch(() => undefined);
    };
  }, [instrument]);

  const analysis = status?.latest_analysis ?? null;
  const analysisQuality = objectValue(analysis?.quality);
  const analysisRoi = objectValue(analysis?.roi);
  const analysisProfile = objectValue(analysis?.processing_profile);
  const warnings = Array.from(new Set([
    ...(status?.warnings ?? []),
    ...textList(analysis, "warnings"),
    ...textList(analysisQuality, "warnings"),
    ...textList(analysisQuality, "flags"),
  ]));
  const frameAge = status?.frame_age_seconds ?? null;
  const stale = frameAge !== null && frameAge > STALE_AFTER_SECONDS;
  const roiCenterX = numberField(analysisRoi, "center_x_px");
  const roiCenterY = numberField(analysisRoi, "center_y_px");
  const roiRadius = numberField(analysisRoi, "radius_px");
  const residual = numberField(analysisRoi, "center_residual_px");
  const glare = numberField(analysisQuality, "glare_fraction");
  const qualityScore = numberField(analysisQuality, "score");
  const calibrationStatus = typeof analysisProfile?.calibration_status === "string"
    ? analysisProfile.calibration_status
    : null;
  const resolution = status?.actual_resolution;
  const currentRoi = status?.analysis_is_current_frame ? status.roi : null;
  const currentCenterX = numberField(currentRoi, "center_x_px");
  const currentCenterY = numberField(currentRoi, "center_y_px");
  const currentRadius = numberField(currentRoi, "radius_px");
  const currentReview = review.frameId === status?.frame_id
    ? review
    : { frameId: status?.frame_id ?? null, confirmed: false, note: "" };

  return (
    <section className="campaign-camera" aria-label="Live campaign camera">
      <div className="campaign-toolbar">
        <h4>Live camera</h4>
        <span className={stale ? "campaign-camera-stale" : "campaign-note"}>
          {frameAge === null ? "Waiting for first frame" : `${frameAge.toFixed(1)} s old${stale ? " · stale" : ""}`}
        </span>
      </div>
      {status?.frame_id !== null && status?.frame_id !== undefined ? (
        <div className="campaign-camera-layout">
          <div className="campaign-camera-frame" style={resolution ? { aspectRatio: `${resolution.width} / ${resolution.height}` } : undefined}>
            <img src={cameraMonitorApi.frameUrl(instrument, status.frame_id)} alt={`Live campaign frame from ${instrument}`} />
            <svg viewBox={`0 0 ${resolution?.width ?? 100} ${resolution?.height ?? 100}`} preserveAspectRatio="none" aria-hidden="true">
              <line x1={(resolution?.width ?? 100) / 2} y1="0" x2={(resolution?.width ?? 100) / 2} y2={resolution?.height ?? 100} className="campaign-optical-center" />
              <line x1="0" y1={(resolution?.height ?? 100) / 2} x2={resolution?.width ?? 100} y2={(resolution?.height ?? 100) / 2} className="campaign-optical-center" />
              {status.expected_center && <circle cx={status.expected_center.x * (resolution?.width ?? 100)} cy={status.expected_center.y * (resolution?.height ?? 100)} r={(resolution?.width ?? 100) * 0.018} className="campaign-expected-center" />}
              {currentCenterX !== null && currentCenterY !== null && <circle cx={currentCenterX} cy={currentCenterY} r={currentRadius ?? (resolution?.width ?? 100) * 0.02} className="campaign-detected-center" />}
            </svg>
          </div>
          <div className="campaign-camera-meta">
            <div><strong>Campaign / trial</strong><span>{status.campaign_id ?? "—"} / {status.trial_number ?? "—"}</span></div>
            <div><strong>Expected well</strong><span>{status.expected_well ?? "—"}</span></div>
            <div><strong>Expected center</strong><span>{status.expected_center ? `${status.expected_center.x.toFixed(3)}, ${status.expected_center.y.toFixed(3)} normalized · operator selected` : "—"}</span></div>
            <div><strong>Step</strong><span>{status.step_index === null ? "—" : `${status.step_index + 1}: ${status.step_command ?? "unknown"}${status.step_substep ? ` · ${status.step_substep}` : ""}`}</span></div>
            <div><strong>Last scored source</strong><span>{analysis ? `${status.analysis_source_run_id ?? "unknown run"} · ${status.analysis_source_well ?? "unknown well"} · frame ${status.analysis_source_frame_id ?? "—"}${status.analysis_is_current_frame ? " · current frame" : " · prior frame"}` : "—"}</span></div>
            <div><strong>Last scored center</strong><span>{roiCenterX === null ? "—" : `${roiCenterX.toFixed(1)}, ${roiCenterY?.toFixed(1)} px${residual === null ? "" : ` · ${residual.toFixed(1)} px residual`}`}</span></div>
            <div><strong>Last scored ROI</strong><span>{roiRadius === null ? "—" : `${roiRadius.toFixed(1)} px radius`}</span></div>
            <div><strong>Last scored quality</strong><span>{qualityScore === null ? "—" : qualityScore.toFixed(2)}{glare === null ? "" : ` · ${(glare * 100).toFixed(1)}% glare`}</span></div>
            <div><strong>Last scored profile</strong><span>{calibrationStatus ?? "not reported"}</span></div>
            {status.analysis_image_url && <div className="campaign-analysis-thumb"><strong>Last scored frame</strong><img src={status.analysis_image_url} alt={`Last scored analysis for ${status.analysis_source_well ?? "campaign well"}`} /></div>}
          </div>
        </div>
      ) : <div className="campaign-note">The campaign owns the camera connection. The monitor will display the latest frame without opening another connection.</div>}

      <div className="campaign-banner campaign-info">
        Expected well comes from the protocol. The red crosshair marks the optical image center; blue marks an operator-selected expected center. Amber ROI appears only when the backend ties analysis to this exact live frame. Computer vision does not verify well identity.
      </div>
      {warnings.length > 0 && <div className="campaign-banner campaign-error" role="alert">{warnings.map((warning) => <div key={warning}>{warning}</div>)}</div>}
      {error && <div className="campaign-banner campaign-error" role="alert">Camera monitor: {error}</div>}

      <div className="campaign-camera-review">
        <label><input type="checkbox" checked={currentReview.confirmed} onChange={(event) => setReview({ ...currentReview, confirmed: event.target.checked })} /> Operator visually confirms the expected well label matches the physical setup for this frame</label>
        <textarea aria-label="Camera review note" value={currentReview.note} onChange={(event) => setReview({ ...currentReview, note: event.target.value })} placeholder="Optional operator note (kept with this open review only)" />
        {(currentReview.confirmed || currentReview.note.trim()) && <small>Local review note for frame {currentReview.frameId ?? "—"}. It does not change calibration, motion, or the campaign result.</small>}
      </div>
    </section>
  );
}
