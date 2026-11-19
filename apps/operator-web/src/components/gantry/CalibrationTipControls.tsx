import { useId } from "react";
import TipMeasurementGuide from "./TipMeasurementGuide";
import * as theme from "../../theme";

type Props = {
  attached: boolean;
  length: string;
  disabled: boolean;
  error: string | null;
  onAttachedChange: (attached: boolean) => void;
  onLengthChange: (length: string) => void;
};

export default function CalibrationTipControls({ attached, length, disabled, error, onAttachedChange, onLengthChange }: Props) {
  const errorId = useId();
  const visibleError = length.trim() ? error : null;
  return <div style={{ margin: "12px 0" }}>
    <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
      <input type="checkbox" checked={attached} disabled={disabled} onChange={(event) => onAttachedChange(event.target.checked)} />
      <span style={theme.fieldLabel}>Tip attached</span>
    </label>
    {attached && <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16, marginTop: 8 }}>
      <div style={{ flex: "0 1 280px", maxWidth: "100%" }}><TipMeasurementGuide /></div>
      <label style={{ display: "grid", gap: 6, flex: "0 1 160px", maxWidth: "100%" }}>
        <span style={theme.fieldLabel}>Measured length (mm)</span>
        <input value={length} required disabled={disabled} inputMode="decimal"
          onChange={(event) => onLengthChange(event.target.value)}
          aria-invalid={visibleError ? true : undefined} aria-describedby={visibleError ? errorId : undefined}
          style={{ ...theme.input, width: 112, maxWidth: "100%" }} />
        {visibleError && <span id={errorId} style={{ color: theme.color.danger, fontSize: 12 }}>{visibleError}</span>}
      </label>
    </div>}
  </div>;
}
