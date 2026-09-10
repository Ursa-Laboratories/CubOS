import { useCallback, useEffect, useState } from "react";
import { instrumentsApi, type LightingChannelInfo } from "../../api/client";
import * as theme from "../../theme";

const CHANNEL_LABELS: Record<string, string> = { white: "White", contact: "LED (contact)" };

export default function LightingControls() {
  const [lights, setLights] = useState<LightingChannelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setLights(await instrumentsApi.listLighting());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const apply = async (body: Parameters<typeof instrumentsApi.setLights>[0]) => {
    setBusy(true);
    try {
      const updated = await instrumentsApi.setLights(body);
      setLights((prev) => prev.map((l) => (l.instrument === updated.instrument ? updated : l)));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (lights.length === 0) {
    return <div style={hintStyle}>{error ?? "No lighting instrument on the connected gantry config."}</div>;
  }

  return (
    <div style={containerStyle}>
      {lights.map((light) => (
        <div key={light.instrument} style={cardStyle}>
          <div style={headerStyle}>
            <span>Lights · {light.instrument}</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => void apply({ instrument: light.instrument, all_off: true })}
              style={offButtonStyle}
            >
              All off
            </button>
          </div>
          {Object.entries(light.channels).map(([channel, levels]) => {
            const active = light.active[channel] ?? 0;
            return (
              <div key={channel} style={rowStyle}>
                <span style={labelStyle}>{CHANNEL_LABELS[channel] ?? channel}</span>
                <div style={levelsStyle}>
                  {[0, ...levels].map((level) => (
                    <button
                      key={level}
                      type="button"
                      disabled={busy}
                      onClick={() => void apply({ instrument: light.instrument, channel, brightness: level })}
                      style={{
                        ...levelButtonStyle,
                        background: active === level ? theme.color.ink : theme.color.surface,
                        color: active === level ? "#fff" : theme.color.ink,
                      }}
                    >
                      {level === 0 ? "Off" : `${level}%`}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      {error && <div style={errorStyle}>{error}</div>}
    </div>
  );
}

const containerStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 };
const cardStyle: React.CSSProperties = {
  border: `1px solid ${theme.color.border}`,
  borderRadius: 8,
  padding: 10,
  background: theme.color.surface,
};
const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  fontSize: 12,
  fontWeight: 600,
  marginBottom: 8,
};
const rowStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" };
const labelStyle: React.CSSProperties = { fontSize: 12, minWidth: 96, color: theme.color.textMuted };
const levelsStyle: React.CSSProperties = { display: "flex", gap: 4, flexWrap: "wrap" };
const levelButtonStyle: React.CSSProperties = {
  border: `1px solid ${theme.color.border}`,
  borderRadius: 6,
  padding: "3px 8px",
  fontSize: 12,
  cursor: "pointer",
};
const offButtonStyle: React.CSSProperties = { ...levelButtonStyle, background: theme.color.surface, color: theme.color.ink };
const hintStyle: React.CSSProperties = { fontSize: 12, color: theme.color.textMuted, marginBottom: 12 };
const errorStyle: React.CSSProperties = { fontSize: 12, color: theme.color.danger };
