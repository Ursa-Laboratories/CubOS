import type { TouchEvent } from "react";
import * as theme from "../../theme";
import JogStepPresets, { type JogStepProps } from "./JogStepPresets";

export default function JogPanel({
  xyStep,
  zStep,
  setXyStep,
  setZStep,
  disabled,
  alarmed,
  onStartJog,
  onStopJog,
}: JogStepProps & {
  disabled: boolean;
  alarmed: boolean;
  onStartJog: (x: number, y: number, z: number) => void;
  onStopJog: () => void;
}) {
  const jogLocked = disabled || alarmed;
  const props = (x: number, y: number, dz: number) => ({
    onMouseDown: () => !jogLocked && onStartJog(x, y, dz),
    onMouseUp: onStopJog,
    onMouseLeave: onStopJog,
    onTouchStart: (event: TouchEvent) => {
      event.preventDefault();
      if (!jogLocked) onStartJog(x, y, dz);
    },
    onTouchEnd: onStopJog,
    onTouchCancel: onStopJog,
  });

  return (
    <div style={jogPanelStyle}>
      <div style={dpadStyle}>
        <div />
        <button style={buttonStateStyle(jogButtonStyle, jogLocked)} disabled={jogLocked} {...props(0, xyStep, 0)} title="Y+">↑</button>
        <div />
        <button style={buttonStateStyle(jogButtonStyle, jogLocked)} disabled={jogLocked} {...props(-xyStep, 0, 0)} title="X-">←</button>
        <div style={padCenterStyle}>XY</div>
        <button style={buttonStateStyle(jogButtonStyle, jogLocked)} disabled={jogLocked} {...props(xyStep, 0, 0)} title="X+">→</button>
        <div />
        <button style={buttonStateStyle(jogButtonStyle, jogLocked)} disabled={jogLocked} {...props(0, -xyStep, 0)} title="Y-">↓</button>
        <div />
      </div>
      <div style={zPadStyle}>
        <button style={buttonStateStyle(jogButtonStyle, jogLocked)} disabled={jogLocked} {...props(0, 0, zStep)} title="Z+">Z+</button>
        <div style={padCenterStyle}>Z</div>
        <button style={buttonStateStyle(jogButtonStyle, jogLocked)} disabled={jogLocked} {...props(0, 0, -zStep)} title="Z-">Z-</button>
      </div>
      <JogStepPresets
        xyStep={xyStep}
        zStep={zStep}
        setXyStep={setXyStep}
        setZStep={setZStep}
        disabled={jogLocked}
      />
    </div>
  );
}

function buttonStateStyle(base: React.CSSProperties, disabled: boolean): React.CSSProperties {
  if (!disabled) return base;
  return {
    ...base,
    opacity: 0.45,
    cursor: "not-allowed",
  };
}

const jogPanelStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 18,
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.md,
  padding: 12,
  width: "fit-content",
  maxWidth: "100%",
  flexWrap: "wrap",
};

const dpadStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3, 40px)",
  gridTemplateRows: "repeat(3, 40px)",
  gap: 2,
};

const zPadStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};

const jogButtonStyle: React.CSSProperties = {
  width: 40,
  height: 40,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: theme.color.surface,
  border: `1px solid ${theme.color.borderStrong}`,
  borderRadius: theme.radius.md,
  color: theme.color.text,
  fontWeight: 600,
  cursor: "pointer",
};

const padCenterStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: theme.color.textFaint,
  fontSize: 10,
};
