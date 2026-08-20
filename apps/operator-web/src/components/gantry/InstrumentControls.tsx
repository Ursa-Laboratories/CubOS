import { useCallback, useEffect, useState } from "react";
import {
  instrumentsApi,
  type CameraInfo,
  type LightingInfo,
} from "../../api/client";
import * as theme from "../../theme";

interface Props {
  /** Gantry session connected — endpoints 400 without it. */
  connected: boolean;
  /** A protocol run is active — manual actuation is rejected mid-run. */
  isRunning?: boolean;
}

/**
 * Manual lighting + camera capture controls for bring-up work.
 *
 * Renders nothing unless the connected gantry config carries a `lighting`
 * or `camera` instrument. Level buttons come from the vendor's declared
 * channel table (never hardcoded here), so a different lighting vendor
 * shows its own levels.
 */
export default function InstrumentControls({ connected, isRunning = false }: Props) {
  const [lighting, setLighting] = useState<LightingInfo[]>([]);
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captureStamp, setCaptureStamp] = useState<Record<string, number>>({});

  const refresh = useCallback(async () => {
    try {
      const [lights, cams] = await Promise.all([
        instrumentsApi.listLighting(),
        instrumentsApi.listCameras(),
      ]);
      setLighting(lights);
      setCameras(cams);
      setError(null);
    } catch {
      // Disconnected gantry or older API — hide the widget rather than error.
      setLighting([]);
      setCameras([]);
    }
  }, []);

  useEffect(() => {
    if (!connected) {
      setLighting([]);
      setCameras([]);
      return;
    }
    void refresh();
  }, [connected, refresh]);

  const setChannel = async (
    instrument: string,
    channel: string,
    brightness: number,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await instrumentsApi.setLights({
        instrument,
        channel,
        brightness,
      });
      setLighting((prev) =>
        prev.map((entry) => (entry.instrument === instrument ? updated : entry)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const allOff = async (instrument: string) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await instrumentsApi.setLights({
        instrument,
        all_off: true,
      });
      setLighting((prev) =>
        prev.map((entry) => (entry.instrument === instrument ? updated : entry)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const capture = async (instrument: string) => {
    setBusy(true);
    setError(null);
    try {
      await instrumentsApi.capture(instrument);
      setCaptureStamp((prev) => ({ ...prev, [instrument]: Date.now() }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!connected || (lighting.length === 0 && cameras.length === 0)) {
    return null;
  }
  const disabled = busy || isRunning;

  return (
    <div style={{ ...theme.card, marginTop: 10 }} data-testid="instrument-controls">
      <div style={theme.sectionLabel}>Instruments</div>
      {isRunning && (
        <div style={{ ...theme.notice.info, marginBottom: 8 }}>
          Manual control is disabled while a protocol run is active.
        </div>
      )}
      {error && <div style={{ ...theme.notice.error, marginBottom: 8 }}>{error}</div>}

      {lighting.map((entry) => (
        <div key={entry.instrument} style={{ marginBottom: 10 }}>
          <div style={theme.fieldLabel}>{entry.instrument} (lights)</div>
          {Object.entries(entry.channels).map(([channel, levels]) => (
            <div
              key={channel}
              style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" }}
            >
              <span style={{ ...theme.mono, minWidth: 64 }}>{channel}</span>
              {levels.map((level) => {
                const active = entry.active[channel] === level;
                return (
                  <button
                    key={level}
                    style={{
                      ...theme.btnSmall,
                      ...(active ? { fontWeight: 700, borderColor: theme.color.accent } : {}),
                    }}
                    disabled={disabled}
                    onClick={() => void setChannel(entry.instrument, channel, level)}
                  >
                    {level}%
                  </button>
                );
              })}
              <button
                style={theme.btnSmall}
                disabled={disabled || entry.active[channel] === 0}
                onClick={() => void setChannel(entry.instrument, channel, 0)}
              >
                off
              </button>
            </div>
          ))}
          <button
            style={{ ...theme.btnSmall, marginTop: 6 }}
            disabled={disabled}
            onClick={() => void allOff(entry.instrument)}
          >
            All lights off
          </button>
        </div>
      ))}

      {cameras.map((entry) => (
        <div key={entry.instrument} style={{ marginBottom: 6 }}>
          <div style={theme.fieldLabel}>
            {entry.instrument} (camera{entry.vendor ? `: ${entry.vendor}` : ""})
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
            <button
              style={theme.btnSmall}
              disabled={disabled}
              onClick={() => void capture(entry.instrument)}
            >
              Capture image
            </button>
            {entry.last_image && (
              <span style={theme.mono} title={entry.last_image}>
                {entry.last_image.split("/").pop()}
              </span>
            )}
          </div>
          {entry.last_image && (
            <img
              src={`${instrumentsApi.lastImageUrl(entry.instrument)}&t=${captureStamp[entry.instrument] ?? 0}`}
              alt={`Last capture from ${entry.instrument}`}
              style={{ marginTop: 6, maxWidth: "100%", maxHeight: 180, borderRadius: 4 }}
            />
          )}
        </div>
      ))}
    </div>
  );
}
