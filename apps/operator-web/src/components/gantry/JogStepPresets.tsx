import * as theme from "../../theme";

const zSteps = [0.1, 0.5, 1, 5, 10, 50] as const;
const xySteps = [...zSteps, 100] as const;

export type ZJogStep = typeof zSteps[number];
export type XYJogStep = typeof xySteps[number];

export interface JogStepProps {
  xyStep: XYJogStep;
  zStep: ZJogStep;
  setXyStep: (value: XYJogStep) => void;
  setZStep: (value: ZJogStep) => void;
}

export default function JogStepPresets({ xyStep, zStep, setXyStep, setZStep, disabled }: JogStepProps & {
  disabled?: boolean;
}) {
  return (
    <div style={{ display: "grid", gap: 6, minWidth: 0, maxWidth: "100%" }}>
      <StepRow axis="XY" values={xySteps} selected={xyStep} onSelect={setXyStep} disabled={disabled} />
      <StepRow axis="Z" values={zSteps} selected={zStep} onSelect={setZStep} disabled={disabled} />
    </div>
  );
}

function StepRow<T extends number>({ axis, values, selected, onSelect, disabled }: {
  axis: "XY" | "Z";
  values: readonly T[];
  selected: T;
  onSelect: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div role="group" aria-label={axis + " jog step (mm)"} style={{
      display: "grid", gridTemplateColumns: "38px minmax(0, 1fr)", gap: 4, alignItems: "center",
    }}>
      <span aria-hidden="true" style={{ ...theme.fieldLabel, whiteSpace: "nowrap" }}>{axis} mm</span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
        {values.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={value === selected}
            disabled={disabled}
            onClick={() => onSelect(value)}
            style={{
              ...theme.btn.secondary,
              ...(value === selected && {
                background: theme.color.accentTint,
                borderColor: theme.color.accentTintBorder,
                color: theme.color.accentText,
                fontWeight: 700,
              }),
              ...theme.mono,
              padding: "3px 5px",
              minWidth: 27,
              minHeight: 24,
              fontSize: 11,
              opacity: disabled ? 0.55 : 1,
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            {value}
          </button>
        ))}
      </div>
    </div>
  );
}
