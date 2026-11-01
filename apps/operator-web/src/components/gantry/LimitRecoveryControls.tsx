import { useCallback, useEffect, useRef, useState } from "react";
import { gantryApi, type LimitRecoveryResult, type RecoveryDelta } from "../../api/client";
import { useLimitRecoveryContext } from "../../hooks/useLimitRecoveryContext";
import type { CalibrationAutoRecovery } from "../../hooks/useCalibrationAutoRecovery";
import * as theme from "../../theme";

type Props = {
  connected: boolean;
  disabled: boolean;
  onStart: () => void;
  onBusyChange: (busy: boolean) => void;
  onRecovered: (result: LimitRecoveryResult) => void;
  onError: (message: string) => void;
  autoRecovery?: CalibrationAutoRecovery;
};

function deltaLabel(delta: RecoveryDelta) {
  return (["x", "y", "z"] as const).filter((axis) => delta[axis] !== 0)
    .map((axis) => `${axis.toUpperCase()}${delta[axis] > 0 ? "+" : "−"} ${Math.abs(delta[axis])} mm`).join(", ");
}

export default function LimitRecoveryControls({ connected, disabled, onStart, onBusyChange, onRecovered, onError, autoRecovery }: Props) {
  const { context, error } = useLimitRecoveryContext(connected);
  const [busy, setBusy] = useState(false);
  const [stopRequested, setStopRequested] = useState(false);
  const [direction, setDirection] = useState<"" | "-1" | "1">("");
  const [pathClear, setPathClear] = useState(false);
  const active = useRef(false);
  const cancelled = useRef(false);
  const mounted = useRef(true);
  const axis = context?.active_limit_axes?.length === 1 ? context.active_limit_axes[0] : null;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (active.current) {
        cancelled.current = true;
        autoRecovery?.cancel();
        void gantryApi.jogCancel().catch(() => undefined);
      }
    };
  }, [autoRecovery]);

  useEffect(() => {
    setDirection("");
    setPathClear(false);
  }, [axis, context?.manual_available]);

  useEffect(() => {
    if (error || !connected) autoRecovery?.cancel();
  }, [autoRecovery, connected, error]);

  const execute = useCallback(async (action: () => Promise<LimitRecoveryResult>, automatic = false) => {
    if (!connected || disabled || active.current) return;
    if (!automatic) autoRecovery?.cancel();
    const lifetime = autoRecovery?.lifetime;
    active.current = true;
    cancelled.current = false;
    setStopRequested(false);
    setBusy(true);
    onBusyChange(true);
    onStart();
    try {
      const result = await action();
      if (!mounted.current || (autoRecovery && autoRecovery.lifetime !== lifetime)) return;
      if (cancelled.current) {
        onError("Recovery stopped. Inspect the gantry before continuing.");
      } else if (result.status !== "recovered") {
        onError(`Recovery did not finish: ${result.status}`);
      } else {
        onRecovered(result);
      }
    } catch (failure) {
      if (mounted.current && (!autoRecovery || autoRecovery.lifetime === lifetime)) onError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      active.current = false;
      setBusy(false);
      setDirection("");
      setPathClear(false);
      if (!autoRecovery || (mounted.current && autoRecovery.lifetime === lifetime)) onBusyChange(false);
    }
  }, [autoRecovery, connected, disabled, onBusyChange, onError, onRecovered, onStart]);

  useEffect(() => {
    const id = context?.failed_jog_id;
    if (!connected || error || disabled || busy || !id || !context.eligible || !context.failed_jog_delta || !context.pull_off_delta || !autoRecovery?.claimFault(id)) return;
    const delta = context.failed_jog_delta;
    void execute(() => gantryApi.recoverCalibrationLimit({ ...delta, jog_id: id }), true);
  }, [autoRecovery, busy, connected, context, disabled, error, execute]);

  const stop = async () => {
    cancelled.current = true;
    autoRecovery?.cancel();
    setStopRequested(true);
    try {
      await gantryApi.jogCancel();
    } catch (failure) {
      onError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (busy) return <button style={theme.btn.danger} disabled={stopRequested} onClick={() => void stop()}>{stopRequested ? "Stopping…" : "Stop recovery"}</button>;

  return <div style={{ display: "grid", gap: 8 }}>
    {error && <span>{error}</span>}
    {!error && !context && <span>Checking recovery…</span>}
    {context?.eligible && context.failed_jog_delta && context.pull_off_delta ? (
      <button style={theme.btn.danger} disabled={disabled || !connected} onClick={() => {
        const delta = context.failed_jog_delta;
        if (delta) void execute(() => gantryApi.recoverCalibrationLimit({ ...delta, jog_id: context.failed_jog_id ?? undefined }));
      }}>Pull off {deltaLabel(context.pull_off_delta)}</button>
    ) : context?.blocked_reason && <span>{context.blocked_reason}</span>}
    {context?.manual_available && axis && <details>
      <summary>Manual recovery</summary>
      <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
        <label>Away direction <select aria-label="Away direction" style={theme.input} disabled={disabled || !connected} value={direction} onChange={(event) => { setDirection(event.target.value as typeof direction); setPathClear(false); }}>
          <option value="">Choose direction</option>
          <option value="-1">{axis.toUpperCase()}−</option>
          <option value="1">{axis.toUpperCase()}+</option>
        </select></label>
        <label><input type="checkbox" checked={pathClear} disabled={disabled || !direction || !connected} onChange={(event) => setPathClear(event.target.checked)} /> Path clear; selected direction moves away from the switch.</label>
        <button style={theme.btn.danger} disabled={disabled || !direction || !pathClear || !connected} onClick={() => {
          if (direction && pathClear) void execute(() => gantryApi.recoverCalibrationLimitManual({ axis, away_direction: direction === "1" ? 1 : -1, operator_confirmed: true }));
        }}>Move {axis.toUpperCase()}{direction ? direction === "1" ? "+" : "−" : ""} 1 mm</button>
      </div>
    </details>}
  </div>;
}
