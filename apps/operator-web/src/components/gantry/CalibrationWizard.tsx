import type { XYJogStep, ZJogStep } from "./JogStepPresets";
import JogPanel from "./JogPanel";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { gantryApi } from "../../api/client";
import * as theme from "../../theme";
import CameraPreview from "./CameraPreview";
import CalibrationTipControls from "./CalibrationTipControls";
import LimitRecoveryControls from "./LimitRecoveryControls";
import type { FinalizeOriginResponse, GantryConfig, GantryPosition, GantryResponse } from "../../types";
import {
  buildCalibratedConfig,
  calculateSingleInstrumentZCalibration,
  getConfiguredHomingPullOff,
  getFactoryZTravel,
  validateFinalizedOrigin,
  type ZCalibrationResult,
} from "./calibrationMath";
import { createJogPacer, jogPaceMs } from "./jogPacing";
import { hasGantryAlarm, isGantryHoming, isVerifiedIdle } from "./gantryAlarm";
import { useCalibrationAutoRecovery } from "../../hooks/useCalibrationAutoRecovery";
import { useLimitRecoveryContext } from "../../hooks/useLimitRecoveryContext";

interface Props {
  open: boolean;
  onClose: () => void;
  gantry: GantryResponse | null;
  position: GantryPosition | null;
  onSaveCalibrated: (filename: string, config: GantryConfig) => Promise<void>;
}

type CapturedPosition = {
  x: number;
  y: number;
  z: number;
};

type JogDelta = {
  x: number;
  y: number;
  z: number;
};

type PendingSingleOrigin = {
  blockTouch: CapturedPosition;
  zReference: CapturedPosition;
};

type PendingZReference = {
  blockTouch: CapturedPosition;
  zReference: CapturedPosition;
  calibration: ZCalibrationResult;
  lowestInstrument: string;
};

const NON_CONTACT_TYPES = new Set(["camera"]);
const FOLLOW_CAMERA_TYPES = new Set(["lighting"]);

function isNonContactInstrument(type: string | undefined): boolean {
  return type != null && NON_CONTACT_TYPES.has(type);
}

function isFollowCameraInstrument(type: string | undefined): boolean {
  return type != null && FOLLOW_CAMERA_TYPES.has(type);
}

export default function CalibrationWizard({
  open,
  onClose,
  gantry,
  position,
  onSaveCalibrated,
}: Props) {
  const autoRecovery = useCalibrationAutoRecovery(open, position?.connected ?? false);
  const [step, setStep] = useState(0);
  const [xyStep, setXyStep] = useState<XYJogStep>(0.5);
  const [zStep, setZStep] = useState<ZJogStep>(0.5);
  const [blockHeight, setBlockHeight] = useState("10");
  const [busy, setBusy] = useState(false);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryCancelRequest, setRecoveryCancelRequest] = useState(0);
  const [jogInFlight, setJogInFlight] = useState(false);
  const [recoveryHomeAvailable, setRecoveryHomeAvailable] = useState(false);
  const [operation, setOperation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alarmPrompt, setAlarmPrompt] = useState<string | null>(null);
  const [statusNote, setStatusNote] = useState<string | null>(null);
  const [xyOrigin, setXyOrigin] = useState<CapturedPosition | null>(null);
  const [zReference, setZReference] = useState<CapturedPosition | null>(null);
  const [blockTouch, setBlockTouch] = useState<CapturedPosition | null>(null);
  const [calibrationHome, setCalibrationHome] = useState<CapturedPosition | null>(null);
  const [zCalibration, setZCalibration] = useState<ZCalibrationResult | null>(null);
  const [xyBounds, setXyBounds] = useState<CapturedPosition | null>(null);
  const [instrumentPositions, setInstrumentPositions] = useState<Record<string, CapturedPosition>>({});
  const [cameraBlockDistances, setCameraBlockDistances] = useState<Record<string, string>>({});
  const [tipAttached, setTipAttached] = useState<Record<string, boolean>>({});
  const [tipLengths, setTipLengths] = useState<Record<string, string>>({});
  const [outputFile, setOutputFile] = useState("");
  const [referenceInstrument, setReferenceInstrument] = useState("");
  const [lowestInstrument, setLowestInstrument] = useState("");
  const jogHeld = useRef<JogDelta | null>(null);
  const jogPumpActive = useRef<object | null>(null);
  const jogRequestCount = useRef(0);
  const pendingJog = useRef<{ cancelled: boolean } | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const previousOpen = useRef(false);
  const previousStep = useRef(step);
  const interruptedStep = useRef<number | null>(null);
  const actionPending = useRef<{ lifetime: number } | null>(null);
  const closePending = useRef<{ lifetime: number } | null>(null);
  const pendingSingleOrigin = useRef<PendingSingleOrigin | null>(null);
  const pendingZReference = useRef<PendingZReference | null>(null);
  const finalizedOrigin = useRef<FinalizeOriginResponse | null>(null);
  const finalizedConfig = useRef<GantryConfig | null>(null);

  const filename = gantry?.filename ?? "";
  const config = gantry?.config ?? null;
  const instruments = useMemo(() => Object.keys(config?.instruments ?? {}), [config]);
  const followCameraInstruments = useMemo(
    () => instruments.filter((name) => isFollowCameraInstrument(config?.instruments[name]?.type)),
    [config, instruments],
  );
  const calibratableInstruments = useMemo(
    () => instruments.filter((name) => !followCameraInstruments.includes(name)),
    [instruments, followCameraInstruments],
  );
  const nonContactInstruments = useMemo(
    () => calibratableInstruments.filter((name) => isNonContactInstrument(config?.instruments[name]?.type)),
    [config, calibratableInstruments],
  );
  const contactInstruments = useMemo(
    () => calibratableInstruments.filter((name) => !nonContactInstruments.includes(name)),
    [calibratableInstruments, nonContactInstruments],
  );
  const defaultTipAttached = useMemo(() => Object.fromEntries(
    instruments.filter((name) => config?.instruments[name]?.type === "pipette").map((name) => [name, true]),
  ), [config, instruments]);
  const isMulti = calibratableInstruments.length > 1;
  const connected = position?.connected ?? false;
  const status = position?.status ?? "";
  const isAlarm = hasGantryAlarm(status);
  const homing = isGantryHoming(status);
  const alarmRecoveryMessage = alarmPrompt ?? (
    isAlarm
      ? status
      : null
  );
  const homeRequired = /home required/i.test(alarmRecoveryMessage ?? "");
  const { context: homeRecoveryContext, error: homeRecoveryError } = useLimitRecoveryContext(open && connected && homeRequired);
  const externallyRecovered = status === "Home required" && !homeRecoveryError
    && homeRecoveryContext?.active_limit_axes?.length === 0
    && /^<?Idle(?:\||>|$)/i.test(homeRecoveryContext.raw_status)
    && !hasGantryAlarm(homeRecoveryContext.raw_status);
  const canHomeAfterRecovery = externallyRecovered || (recoveryHomeAvailable && !!position && isVerifiedIdle(position));
  const normalizedOutput = outputFile.trim() || defaultOutputFilename(filename);
  const selectedReference = referenceInstrument || contactInstruments[0] || "";
  const selectedLowest = lowestInstrument || contactInstruments[0] || "";
  const instrumentSequence = useMemo(
    () => unique([selectedReference, ...calibratableInstruments]).filter((name) => name && name !== selectedLowest),
    [calibratableInstruments, selectedLowest, selectedReference],
  );
  const nextInstrumentToRecord = instrumentSequence.find((name) => !instrumentPositions[name]) ?? null;
  const nextInstrumentIsCamera = nextInstrumentToRecord ? nonContactInstruments.includes(nextInstrumentToRecord) : false;
  const nextCameraDistanceError = nextInstrumentIsCamera && nextInstrumentToRecord
    ? validateCameraBlockDistance(cameraBlockDistances[nextInstrumentToRecord])
    : null;
  const nextInstrumentIsPipette = nextInstrumentToRecord
    ? config?.instruments[nextInstrumentToRecord]?.type === "pipette"
    : false;
  const nextInstrumentTipAttached = nextInstrumentToRecord ? !!tipAttached[nextInstrumentToRecord] : false;
  const nextTipLengthError = nextInstrumentTipAttached && nextInstrumentToRecord
    ? validateTipLength(tipLengths[nextInstrumentToRecord])
    : null;
  // The lowest/reference instrument's block touch feeds directly into the Z
  // working-volume bounds (see calculateSingleInstrumentZCalibration) for
  // both flows, so it needs the same tip-attached compensation as any other
  // pipette touch, not just the non-reference instruments recorded above.
  const referenceInstrumentIsPipette = config?.instruments[selectedReference]?.type === "pipette";
  const referenceTipAttached = referenceInstrumentIsPipette && !!tipAttached[selectedReference];
  const referenceTipLengthError = isMulti && referenceTipAttached ? validateTipLength(tipLengths[selectedReference]) : null;
  const lowestInstrumentIsPipette = selectedLowest
    ? config?.instruments[selectedLowest]?.type === "pipette"
    : false;
  const lowestTipAttached = lowestInstrumentIsPipette && !!tipAttached[selectedLowest];
  const lowestTipLengthError = lowestTipAttached ? validateTipLength(tipLengths[selectedLowest]) : null;
  const soleInstrument = !isMulti ? (instruments[0] ?? "") : "";
  const soleInstrumentIsPipette = soleInstrument
    ? config?.instruments[soleInstrument]?.type === "pipette"
    : false;
  const soleTipAttached = soleInstrumentIsPipette && !!tipAttached[soleInstrument];
  const soleTipLengthError = soleTipAttached ? validateTipLength(tipLengths[soleInstrument]) : null;
  const readyForSave = isMulti
    ? !!zReference && !!zCalibration && allInstrumentPositionsReady(calibratableInstruments, instrumentPositions, selectedReference, selectedLowest)
    : !!zReference && !!blockTouch && !!calibrationHome;
  const controlsLocked = busy || jogInFlight || homing || !!alarmRecoveryMessage;

  useEffect(() => {
    const wasOpen = previousOpen.current;
    previousOpen.current = open;
    if (!open || wasOpen) return;
    setStep(0);
    setBusy(false);
    setRecoveryBusy(false);
    setRecoveryHomeAvailable(false);
    interruptedStep.current = null;
    setOperation(null);
    setError(null);
    setAlarmPrompt(null);
    setStatusNote(null);
    setXyOrigin(null);
    setZReference(null);
    setBlockTouch(null);
    setCalibrationHome(null);
    setZCalibration(null);
    setXyBounds(null);
    setInstrumentPositions({});
    setCameraBlockDistances({});
    setTipAttached(defaultTipAttached);
    setTipLengths({});
    setOutputFile(defaultOutputFilename(filename));
    setReferenceInstrument(contactInstruments[0] ?? "");
    setLowestInstrument(contactInstruments[0] ?? "");
    setBlockHeight(formatOptionalNumber(config?.cnc.calibration_block_height_mm));
    jogRequestCount.current = 0;
    pendingSingleOrigin.current = null;
    pendingZReference.current = null;
    finalizedOrigin.current = null;
    finalizedConfig.current = null;
  }, [config?.cnc.calibration_block_height_mm, contactInstruments, defaultTipAttached, filename, open]);

  useEffect(() => {
    if (!open || statusNote !== "Homed.") return;
    const timer = window.setTimeout(() => {
      setStatusNote((current) => current === "Homed." ? null : current);
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [open, statusNote]);

  useEffect(() => {
    const priorStep = previousStep.current;
    previousStep.current = step;
    if (priorStep === step) return;
    if (step !== 3) {
      pendingSingleOrigin.current = null;
    }
    if (step !== 4) {
      pendingZReference.current = null;
    }
  }, [step]);

  const jogPacer = useRef(createJogPacer()).current;

  const haltJogLocally = useCallback(() => {
    jogHeld.current = null;
    jogRequestCount.current = 0;
    jogPacer.wake();
  }, [jogPacer]);

  const stopJog = useCallback((force = false) => {
    if (jogHeld.current === null && !force) return;
    jogHeld.current = null;
    if ((force || jogRequestCount.current > 1) && pendingJog.current && !pendingJog.current.cancelled) {
      pendingJog.current.cancelled = true;
      autoRecovery.cancel();
      gantryApi.jogCancel().catch(() => undefined);
    }
    jogRequestCount.current = 0;
    jogPacer.wake();
  }, [autoRecovery, jogPacer]);

  const releaseJog = useCallback(() => {
    if (alarmRecoveryMessage) haltJogLocally();
    else stopJog();
  }, [alarmRecoveryMessage, haltJogLocally, stopJog]);

  useEffect(() => {
    if (!open) return;
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") releaseJog();
    };
    window.addEventListener("mouseup", releaseJog);
    window.addEventListener("blur", releaseJog);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("mouseup", releaseJog);
      window.removeEventListener("blur", releaseJog);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [open, releaseJog]);

  useEffect(() => {
    if (!open) return;
    return () => stopJog(true);
  }, [open, stopJog]);

  const invalidateCaptures = useCallback(() => {
    interruptedStep.current ??= previousStep.current;
    setXyOrigin(null);
    setZReference(null);
    setBlockTouch(null);
    setCalibrationHome(null);
    setZCalibration(null);
    setXyBounds(null);
    setInstrumentPositions({});
    pendingSingleOrigin.current = null;
    pendingZReference.current = null;
    finalizedOrigin.current = null;
    finalizedConfig.current = null;
  }, []);

  useEffect(() => {
    if (!open || !connected || !isAlarm) return;
    haltJogLocally();
    invalidateCaptures();
    setAlarmPrompt(status);
    setStatusNote(null);
    if (!/home required/i.test(status)) setRecoveryHomeAvailable(false);
  }, [connected, haltJogLocally, invalidateCaptures, isAlarm, open, status]);

  const reportError = useCallback((err: unknown) => {
    const message = err instanceof Error ? err.message : String(err);
    if (looksLikeAlarm(message)) {
      haltJogLocally();
      invalidateCaptures();
      setStatusNote(null);
      setRecoveryHomeAvailable(false);
      setAlarmPrompt(
        "The gantry is in an alarm state. Clear it before continuing.",
      );
    } else stopJog();
    setError(message);
  }, [haltJogLocally, invalidateCaptures, stopJog]);

  const clearPendingCaptures = () => {
    pendingSingleOrigin.current = null;
    pendingZReference.current = null;
    finalizedOrigin.current = null;
    finalizedConfig.current = null;
  };

  const resetFlow = () => {
    autoRecovery.begin();
    setRecoveryBusy(false);
    setRecoveryHomeAvailable(false);
    interruptedStep.current = null;
    setStep(0);
    setOperation(null);
    setError(null);
    setAlarmPrompt(null);
    setStatusNote(null);
    setXyOrigin(null);
    setZReference(null);
    setBlockTouch(null);
    setCalibrationHome(null);
    setZCalibration(null);
    setXyBounds(null);
    setInstrumentPositions({});
    setCameraBlockDistances({});
    setTipAttached(defaultTipAttached);
    setTipLengths({});
    setOutputFile(defaultOutputFilename(filename));
    setReferenceInstrument(contactInstruments[0] ?? "");
    setLowestInstrument(contactInstruments[0] ?? "");
    clearPendingCaptures();
    jogRequestCount.current = 0;
  };

  const reset = async () => {
    if (busy) return;
    autoRecovery.end();
    stopJog(true);
    let restoreError: string | null = null;
    if (connected) {
      try {
        await gantryApi.restoreCalibrationSoftLimits();
      } catch (err) {
        restoreError = `Failed to restore soft limits: ${err instanceof Error ? err.message : String(err)}. Reconnect before running protocols.`;
      }
    }
    // Reset even when the restore failed (e.g. the serial link died after
    // a limit crash) — refusing traps the operator in a wizard whose every
    // exit needs a controller round-trip. The session still tracks the
    // un-restored state and the gantry widget's CALIBRATION INTERRUPTED
    // banner offers the retry.
    resetFlow();
    if (restoreError) {
      setError(restoreError);
    }
  };

  const close = useCallback(async () => {
    if (closePending.current?.lifetime === autoRecovery.lifetime) return;
    autoRecovery.end();
    const request = { lifetime: autoRecovery.lifetime };
    closePending.current = request;
    stopJog(!recoveryBusy);
    if (recoveryBusy) {
      try {
        await gantryApi.jogCancel();
      } catch (failure) {
        if (autoRecovery.lifetime === request.lifetime) setError(errorMessage(failure));
      }
    }
    if (!connected) {
      if (autoRecovery.lifetime === request.lifetime) onClose();
      if (closePending.current === request) closePending.current = null;
      return;
    }
    try {
      await gantryApi.restoreCalibrationSoftLimits();
    } catch {
      // Closing must never be gated on a controller round-trip. If the
      // restore failed, calibration_active stays true on the session and
      // the gantry widget's CALIBRATION INTERRUPTED banner takes over
      // until soft limits are actually restored.
    }
    if (autoRecovery.lifetime === request.lifetime) onClose();
    if (closePending.current === request) closePending.current = null;
  }, [autoRecovery, connected, onClose, recoveryBusy, stopJog]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!event.repeat && (!busy || recoveryBusy || jogInFlight)) void close();
        return;
      }
      const target = event.target;
      if (event.key !== " " || (target instanceof HTMLElement && (target.isContentEditable || target.closest("input:not(:disabled), textarea:not(:disabled), select:not(:disabled)")))) return;
      if (!recoveryBusy && !jogInFlight) return;
      event.preventDefault();
      if (event.repeat || closePending.current) return;
      if (recoveryBusy) {
            setRecoveryCancelRequest((current) => current + 1);
      } else {
        stopJog(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, close, jogInFlight, open, recoveryBusy, stopJog]);

  useEffect(() => {
    if (!open || step < 2) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
      return "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [open, step]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const focusTimer = window.setTimeout(() => {
      dialogRef.current?.focus();
    }, 0);
    return () => {
      window.clearTimeout(focusTimer);
      previousFocusRef.current?.focus();
    };
  }, [open]);

  const handleDialogKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab") return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = getFocusableElements(dialog);
    if (focusable.length === 0) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const activeIsFocusable = active ? focusable.includes(active) : false;
    if (event.shiftKey && (!activeIsFocusable || active === first)) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && (!activeIsFocusable || active === last)) {
      event.preventDefault();
      first.focus();
    }
  };

  const runAction = async (label: string, action: (generation: number) => Promise<void>) => {
    const generation = autoRecovery.generation;
    const lifetime = autoRecovery.lifetime;
    if (!autoRecovery.active || actionPending.current?.lifetime === lifetime) return;
    const request = { lifetime };
    actionPending.current = request;
    setBusy(true);
    setOperation(label);
    setError(null);
    try {
      await action(generation);
    } catch (err) {
      if (actionPending.current === request && autoRecovery.active && autoRecovery.lifetime === lifetime) reportError(err);
    } finally {
      if (actionPending.current === request) {
        actionPending.current = null;
        if (autoRecovery.active && autoRecovery.lifetime === lifetime) {
          setOperation(null);
          setBusy(false);
        }
      }
    }
  };

  const assertGeneration = (generation: number) => {
    if (!autoRecovery.active || autoRecovery.generation !== generation) throw new Error("Calibration closed.");
  };

  const jogBlocking = async (delta: JogDelta, timeout_s: number, generation: number) => {
    const id = autoRecovery.issueJogId(generation);
    if (!id) throw new Error("Calibration closed.");
    const request = { cancelled: false };
    pendingJog.current = request;
    setJogInFlight(true);
    try {
      await gantryApi.jogBlocking(delta.x, delta.y, delta.z, timeout_s, id);
      assertGeneration(generation);
    } catch (failure) {
      if (autoRecovery.active && autoRecovery.generation === generation) {
        invalidateCaptures();
        if (!looksLikeAlarm(errorMessage(failure))) autoRecovery.cancel();
      }
      throw failure;
    } finally {
      if (pendingJog.current === request) {
        pendingJog.current = null;
        setJogInFlight(false);
      }
    }
  };

  // Step 0 → 1: just navigate, no hardware action yet.
  const goToHome = () => {
    if (!filename || instruments.length === 0) return;
    if (isMulti && contactInstruments.length === 0) {
      setError("Multi-instrument calibration requires at least one contact-capable instrument.");
      return;
    }
    if (isMulti && config) {
      try {
        // Missing homing_pull_off now falls back to a default; this only
        // catches an explicitly invalid (negative/non-finite) value.
        getConfiguredHomingPullOff(config);
      } catch (err) {
        setError(
          `grbl_settings.homing_pull_off in the gantry YAML is invalid. ` +
          `Fix the config and save before calibrating. (${errorMessage(err)})`,
        );
        return;
      }
    }
    setStatusNote(null);
    setStep(1);
  };

  // Step 1: connect (if needed) then home. This is the first hardware action.
  const homeForCalibration = (resume = false) => runAction("Homing", async (generation) => {
    const resumeFrom = resume ? interruptedStep.current : null;
    invalidateCaptures();
    if (!filename) throw new Error("Select a gantry config first.");
    if (!connected) {
      await gantryApi.connect(filename);
      assertGeneration(generation);
    }
    const result = await gantryApi.prepareCalibrationOrigin();
    assertGeneration(generation);
    if (!isVerifiedIdle(result)) throw new Error(`Homing is unverified: ${result.status}`);
    const homed = requirePosition(result);
    pendingJog.current = null;
    jogPumpActive.current = null;
    setJogInFlight(false);
    setAlarmPrompt(null);
    setRecoveryHomeAvailable(false);
    setCalibrationHome(homed);
    setStatusNote("Homed.");
    interruptedStep.current = null;
    setStep(!isMulti && resumeFrom != null && resumeFrom >= 3 ? 3 : 2);
  });

  const setXY = () => runAction(
    "Setting XY origin",
    async (generation) => {
    if (referenceTipLengthError) throw new Error(referenceTipLengthError);
    const result = await gantryApi.setWorkCoordinates({ x: 0, y: 0 });
    assertGeneration(generation);
    const captured = requirePosition(result);
    setXyOrigin(captured);
    const centered = await gantryApi.homeAndCenterForCalibration();
    assertGeneration(generation);
    setXyBounds(capturedFromPlain(centered.xy_bounds));
    setStatusNote("XY origin set.");
    setStep(3);
  });

  // Shared "Block height" step handler for both flows: validate the
  // entered height, then advance (single → Set origin, multi → Z ref).
  const continueFromBlockHeight = (nextStep: number) => {
    setError(null);
    try {
      parseBlockHeight(blockHeight);
    } catch (err) {
      setError(errorMessage(err));
      return;
    }
    setStatusNote(null);
    setStep(nextStep);
  };

  const setSingleInstrumentOrigin = () => runAction("Setting origin", async (generation) => {
    if (!config) throw new Error("No gantry config is loaded.");
    let pending = pendingSingleOrigin.current;
    if (!pending) {
      const height = parseBlockHeight(blockHeight);
      const blockTouch = requirePosition(await gantryApi.getPosition());
      assertGeneration(generation);
      // Set WPos before restoring soft limits: if setWorkCoordinates fails,
      // soft limits stay disabled so the operator can still jog freely and
      // retry. Once this succeeds, retries must not re-capture in the shifted
      // frame.
      const result = await gantryApi.setWorkCoordinates({ x: 0, y: 0, z: height });
      assertGeneration(generation);
      pending = {
        blockTouch,
        zReference: requirePosition(result),
      };
      pendingSingleOrigin.current = pending;
    }
    await gantryApi.restoreCalibrationSoftLimits();
    assertGeneration(generation);
    setBlockTouch(pending.blockTouch);
    setZReference(pending.zReference);
    setZCalibration(null);
    setStatusNote("Origin set.");
    setStep(4);
  });

  const setZ = () => runAction(
    isMulti && selectedLowest
      ? `Setting Z reference with ${selectedLowest}`
      : "Setting Z reference",
    async (generation) => {
    if (!config) throw new Error("No gantry config is loaded.");
    let pending = pendingZReference.current;
    if (!pending) {
      const height = parseBlockHeight(blockHeight);
      const factoryZTravel = getFactoryZTravel(config);
      // Travel uses carriage readbacks; tip extension belongs in tool depth.
      const blockTouch = requirePosition(await gantryApi.getPosition());
      assertGeneration(generation);
      const homeZ = isMulti
        ? requireCaptured(xyBounds, "Homed XY bounds")
        : requireCaptured(calibrationHome, "Home position");
      const calibration = calculateSingleInstrumentZCalibration({
        homeZ,
        blockTouchZ: blockTouch.z,
        blockHeight: height,
        factoryZTravel,
      });
      const result = await gantryApi.setWorkCoordinates({ z: height });
      assertGeneration(generation);
      pending = {
        blockTouch,
        zReference: requirePosition(result),
        calibration,
        lowestInstrument: selectedLowest,
      };
      pendingZReference.current = pending;
    }
    setZReference(pending.zReference);
    setZCalibration(pending.calibration);
    if (isMulti && pending.lowestInstrument) {
      setInstrumentPositions((prev) => ({ ...prev, [pending.lowestInstrument]: pending.zReference }));
      await jogBlocking({ x: 0, y: 0, z: 15 }, 15, generation);
      assertGeneration(generation);
      setStatusNote(`Recorded ${pending.lowestInstrument}.`);
    } else {
      setStatusNote("Z reference set.");
    }
    setStep(isMulti ? 5 : 3);
  });

  const recordCurrentInstrument = (name: string) => runAction(
    `Recording ${name}`,
    async (generation) => {
    if (!name) return;
    const isCamera = nonContactInstruments.includes(name);
    if (isCamera) {
      const message = validateCameraBlockDistance(cameraBlockDistances[name]);
      if (message) throw new Error(message);
    }
    if (tipAttached[name]) {
      const message = validateTipLength(tipLengths[name]);
      if (message) throw new Error(message);
    }
    const captured = requirePosition(await gantryApi.getPosition());
    assertGeneration(generation);
    const nextPositions = { ...instrumentPositions, [name]: captured };
    setInstrumentPositions(nextPositions);
    if (isCamera) {
      setStatusNote(`Recorded ${name}.`);
      if (allInstrumentPositionsReady(calibratableInstruments, nextPositions, selectedReference, selectedLowest)) {
        setStep(6);
      }
      return;
    }
    await jogBlocking({ x: 0, y: 0, z: 15 }, 15, generation);
    assertGeneration(generation);
    setStatusNote(`Recorded ${name}.`);
    if (allInstrumentPositionsReady(calibratableInstruments, nextPositions, selectedReference, selectedLowest)) {
      setStep(6);
    }
  });

  const save = () => runAction("Measuring travel and saving", async (generation) => {
    if (!config) throw new Error("No gantry config is loaded.");
    if (!readyForSave) throw new Error("Complete the calibration positions before saving.");
    if (!finalizedConfig.current) {
      const deckConfig: GantryConfig = { ...config, origin_policy: "deck_origin" };
      const initial = isMulti ? requireZCalibration(zCalibration) : null;
      if (!finalizedOrigin.current) {
        finalizedOrigin.current = await gantryApi.finalizeCalibrationOrigin({
          home_z: initial?.homeZ ?? requireCaptured(calibrationHome, "Home position"),
          block_touch_z: initial?.blockTouchZ ?? requireCaptured(blockTouch, "Block touch position"),
          block_height: initial?.blockHeight ?? parseBlockHeight(blockHeight),
          factory_z_travel: initial?.factoryZTravel ?? getFactoryZTravel(config),
          origin_policy: deckConfig.origin_policy,
        });
        assertGeneration(generation);
      }
      const finalized = finalizedOrigin.current;
      const verifiedVolume = validateFinalizedOrigin(deckConfig, finalized);
      const calibrated = buildCalibratedConfig({
        config: {
          ...deckConfig,
          cnc: {
            ...config.cnc,
            calibration_block_height_mm: finalized.z_calibration.block_height,
          },
          grbl_settings: {
            ...(config.grbl_settings ?? {}),
            homing_pull_off: finalized.homing_pull_off_mm ?? config.grbl_settings?.homing_pull_off,
          },
        },
        measuredVolume: capturedFromPlain(finalized.measured_volume),
        zMin: finalized.z_calibration.z_min,
        zMax: finalized.z_calibration.z_max,
        maxTravel: capturedFromPlain(finalized.max_travel),
        isMulti,
        instruments,
        instrumentPositions,
        referenceInstrument: selectedReference,
        lowestInstrument: selectedLowest,
        cameraBlockDistances: parsedCameraBlockDistances(cameraBlockDistances, nonContactInstruments),
        tipLengths: parsedTipLengths(tipLengths, tipAttached),
      });
      calibrated.working_volume = verifiedVolume;
      calibrated.cnc.safe_z = finalized.safe_z;
      finalizedConfig.current = calibrated;
    }
    await onSaveCalibrated(normalizedOutput, structuredClone(finalizedConfig.current));
    assertGeneration(generation);
    autoRecovery.end();
    onClose();
  });

  const jog = useCallback(async (x: number, y: number, z: number, generation = autoRecovery.generation): Promise<boolean> => {
    if (!open || !connected || busy || homing || alarmRecoveryMessage) return false;
    const id = autoRecovery.issueJogId(generation);
    if (!id) return false;
    const request = { cancelled: false };
    pendingJog.current = request;
    setJogInFlight(true);
    jogRequestCount.current += 1;
    try {
      const configuredRates = (["x", "y", "z"] as const).filter((axis) => ({ x, y, z })[axis] !== 0)
        .map((axis) => config?.grbl_settings?.[`max_rate_${axis}`])
        .filter((rate): rate is number => typeof rate === "number" && Number.isFinite(rate) && rate > 0);
      const rate = Math.min(2000, ...configuredRates);
      const timeout = Math.max(15, Math.hypot(x, y, z) * 60 / rate + 5);
      await gantryApi.jogBlocking(x, y, z, timeout, id);
      return autoRecovery.active && autoRecovery.generation === generation;
    } catch (err) {
      if (!autoRecovery.active || autoRecovery.generation !== generation) return false;
      invalidateCaptures();
      if (!looksLikeAlarm(errorMessage(err))) autoRecovery.cancel();
      reportError(err);
      return false;
    } finally {
      if (pendingJog.current === request) {
        pendingJog.current = null;
        setJogInFlight(false);
      }
    }
  }, [alarmRecoveryMessage, autoRecovery, busy, config?.grbl_settings, connected, homing, invalidateCaptures, open, reportError]);

  // The held-jog pump reads jog through a ref so an in-flight hold always
  // uses the latest guards (alarm/busy state) instead of a stale closure.
  const jogRef = useRef(jog);
  useEffect(() => {
    jogRef.current = jog;
  }, [jog]);

  const startJog = (x: number, y: number, z: number) => {
    if (busy || homing || alarmRecoveryMessage) return;
    const generation = autoRecovery.generation;
    const heldBefore = jogHeld.current !== null;
    if (jogPumpActive.current) {
      if (!heldBefore) return;
      jogHeld.current = { x, y, z };
      // Direction change mid-hold: hand the new delta to the pump instead
      // of firing immediately — an immediate send would repeat at the
      // previous segment's pace, and with soft limits off during
      // calibration that backlog runs the gantry into the hard-limit
      // switches. wake() cuts the remaining sleep so the new direction
      // still starts promptly.
      jogPacer.wake();
      return;
    }
    jogHeld.current = { x, y, z };
    jogRequestCount.current = 0;
    const first = jogRef.current(x, y, z, generation);
    const pumpToken = {};
    jogPumpActive.current = pumpToken;
    const pump = async () => {
      try {
        let sent = { x, y, z };
        let ok = await first;
        while (ok && jogHeld.current && autoRecovery.generation === generation) {
          // Held repeats stay one-in-flight, paced by the segment actually
          // sent last (the held delta can change mid-hold) — soft limits
          // are off during calibration, so an unbounded jog backlog here
          // runs the gantry into the hard-limit switches.
          await jogPacer.sleep(jogPaceMs(sent.x, sent.y, sent.z));
          const delta = jogHeld.current;
          if (!delta) break;
          sent = delta;
          ok = await jogRef.current(delta.x, delta.y, delta.z, generation);
        }
        if (!ok) {
          jogHeld.current = null;
        }
      } finally {
        if (jogPumpActive.current === pumpToken) jogPumpActive.current = null;
      }
    };
    void pump();
  };

  if (!open) return null;

  const referenceTipControls = isMulti && referenceInstrumentIsPipette ? (
    <CalibrationTipControls attached={referenceTipAttached} length={tipLengths[selectedReference] ?? ""}
      disabled={controlsLocked} error={referenceTipLengthError}
      onAttachedChange={(attached) => setTipAttached((prev) => ({ ...prev, [selectedReference]: attached }))}
      onLengthChange={(length) => setTipLengths((prev) => ({ ...prev, [selectedReference]: length }))} />
  ) : null;

  return (
    <div
      ref={dialogRef}
      style={overlayStyle}
      role="dialog"
      aria-modal="true"
      aria-label="Gantry calibration"
      tabIndex={-1}
      onKeyDown={handleDialogKeyDown}
    >
      <div style={modalStyle}>
        <div style={headerStyle}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18, color: theme.color.ink, letterSpacing: "-0.01em" }}>Calibrate gantry</h2>
            <div style={{ marginTop: 3, fontSize: 12, color: theme.color.textMuted }}>
              {filename || "No file selected"}
            </div>
          </div>
          <div style={headerActionsStyle}>
            <button
              onClick={() => void reset()}
              disabled={busy}
              style={buttonStateStyle(buttonStyle, busy)}
            >
              Reset wizard
            </button>
            <button
              onClick={close}
              style={closeButtonStyle}
              aria-label="Close calibration"
            >
              ×
            </button>
          </div>
        </div>

        <div style={bodyStyle}>
          <aside style={stepsStyle}>
            {stepLabels(isMulti).map((label, index) => (
              <div
                key={label}
                style={index === step ? activeStepStyle : index < step ? completedStepStyle : stepButtonStyle}
                aria-current={index === step ? "step" : undefined}
              >
                <span style={stepNumberStyle}>{index + 1}</span>
                {label}
              </div>
            ))}
          </aside>

          <section style={contentStyle}>
            {alarmRecoveryMessage && (
              <div style={alarmStyle}>
                <span style={alarmTitleStyle}>GANTRY ALARM</span>
                <span>{alarmRecoveryMessage}</span>
                {(!homeRequired || recoveryBusy) && <LimitRecoveryControls
                  automaticOnly
                  cancelRequest={recoveryCancelRequest}
                  connected={connected} disabled={homing || (busy && !jogInFlight)}
                  onStart={() => {
                    haltJogLocally();
                    if (pendingJog.current) pendingJog.current.cancelled = true;
                    setError(null);
                  }}
                  autoRecovery={autoRecovery}
                  onBusyChange={(value) => { setRecoveryBusy(value); setBusy(value); }}
                  onRecovered={() => {
                    actionPending.current = null;
                    autoRecovery.cancel();
                    pendingJog.current = null;
                    jogPumpActive.current = null;
                    setJogInFlight(false);
                    invalidateCaptures();
                    setError(null);
                    setRecoveryHomeAvailable(true);
                    setAlarmPrompt("Home required. Clear the gantry path before homing.");
                    setStatusNote("Pull-off complete.");
                  }}
                  onError={(message) => { actionPending.current = null; autoRecovery.cancel(); setError(message); }}
                />}
                {canHomeAfterRecovery && <button
                  onClick={() => void homeForCalibration(true)}
                  disabled={busy || homing || !connected || (isAlarm && !/home required/i.test(status))}
                  style={buttonStateStyle(alarmButtonStyle, busy || homing || !connected || (isAlarm && !/home required/i.test(status)))}
                >
                  {isMulti ? "Home and restart calibration" : "Home and resume"}
                </button>}
              </div>
            )}
            {error && <div style={errorStyle}>{error}</div>}
            {operation && <div style={busyStyle}>{operation}… Please wait.</div>}
            {statusNote && <div style={noteStyle}>{statusNote}</div>}

            {step === 0 && (
              <div>
                <h3 style={sectionTitleStyle}>Prepare</h3>
                <p style={instructionStyle}>
                  {isMulti
                    ? "Choose a file name for the calibrated config, pick the leftmost and lowest instruments, then continue."
                    : "Choose a file name for the calibrated config, then continue."}
                </p>
                {isMulti && (
                  <p style={instructionStyle}>
                    Choose the physically leftmost contact instrument as viewed from
                    the front of the gantry. It defines zero X/Y offset. Choose the
                    lowest instrument separately to define Z; they may be the same tool.
                  </p>
                )}
                {instruments.length === 0 && (
                  <div style={noInstrumentsStyle}>
                    Add and save at least one mounted instrument in the Gantry configuration before calibrating.
                  </div>
                )}
                <div style={fieldRowStyle}>
                  <label style={fieldStyle}>
                    <span style={labelStyle}>Output YAML</span>
                    <input
                      value={outputFile}
                      onChange={(event) => setOutputFile(event.target.value)}
                      disabled={controlsLocked}
                      style={buttonStateStyle(inputStyle, controlsLocked)}
                    />
                  </label>
                  {isMulti && (
                    <>
                      <label style={fieldStyle}>
                        <span style={labelStyle}>Leftmost instrument</span>
                        <select
                          value={selectedReference}
                          onChange={(event) => setReferenceInstrument(event.target.value)}
                          disabled={controlsLocked}
                          style={buttonStateStyle(inputStyle, controlsLocked)}
                        >
                          {contactInstruments.map((name) => <option key={name} value={name}>{name}</option>)}
                        </select>
                      </label>
                      <label style={fieldStyle}>
                        <span style={labelStyle}>Lowest instrument</span>
                        <select
                          value={selectedLowest}
                          onChange={(event) => setLowestInstrument(event.target.value)}
                          disabled={controlsLocked}
                          style={buttonStateStyle(inputStyle, controlsLocked)}
                        >
                          {contactInstruments.map((name) => <option key={name} value={name}>{name}</option>)}
                        </select>
                      </label>
                    </>
                  )}
                </div>
                {referenceTipControls}
                <div style={actionRowStyle}>
                  <button onClick={goToHome} disabled={controlsLocked || !filename || instruments.length === 0 || !!referenceTipLengthError} style={buttonStateStyle(primaryButtonStyle, controlsLocked || !filename || instruments.length === 0 || !!referenceTipLengthError)}>Continue</button>
                </div>
              </div>
            )}

            {step === 1 && (
              <div>
                <h3 style={sectionTitleStyle}>Home gantry</h3>
                <p style={instructionStyle}>
                  Clear the deck so nothing is in the gantry's path, then home.
                </p>
                <div style={actionRowStyle}>
                  <button onClick={() => void homeForCalibration()} disabled={controlsLocked} style={buttonStateStyle(primaryButtonStyle, controlsLocked)}>Home gantry</button>
                </div>
              </div>
            )}

            {!isMulti && step === 2 && (
              <div>
                <h3 style={sectionTitleStyle}>Calibration Reference Height</h3>
                <p style={instructionStyle}>
                  Enter the height of your calibration block above the deck. If you are touching another surface instead (for example the top of a plate), enter its height from the deck.
                </p>
                <div style={fieldRowStyle}>
                  <label style={fieldStyle}>
                    <span style={labelStyle}>Reference height (mm)</span>
                    <input
                      value={blockHeight}
                      onChange={(event) => setBlockHeight(event.target.value)}
                      style={inputStyle}
                      inputMode="decimal"
                      autoFocus
                    />
                  </label>
                </div>
                <div style={actionRowStyle}>
                  <button onClick={() => continueFromBlockHeight(3)} disabled={controlsLocked} style={buttonStateStyle(primaryButtonStyle, controlsLocked)}>Continue</button>
                </div>
              </div>
            )}

            {!isMulti && step === 3 && (
              <div>
                <h3 style={sectionTitleStyle}>Set Origin</h3>
                <p style={instructionStyle}>
                  Place the block at the front-left corner of the deck. Jog {soleTipAttached ? "the tip" : "the tool"} to touch its top, then set origin.
                </p>
                {soleInstrumentIsPipette && (
                  <CalibrationTipControls attached={soleTipAttached} length={tipLengths[soleInstrument] ?? ""}
                    disabled={controlsLocked} error={soleTipLengthError}
                    onAttachedChange={(attached) => setTipAttached((prev) => ({ ...prev, [soleInstrument]: attached }))}
                    onLengthChange={(length) => setTipLengths((prev) => ({ ...prev, [soleInstrument]: length }))} />
                )}
                <JogPanel
                  xyStep={xyStep}
                  zStep={zStep}
                  setXyStep={setXyStep}
                  setZStep={setZStep}
                  disabled={!connected || busy || homing || !!alarmRecoveryMessage}
                  alarmed={!!alarmRecoveryMessage}
                  onStartJog={startJog}
                  onStopJog={releaseJog}
                />
                <div style={actionRowStyle}>
                  <button
                    onClick={setSingleInstrumentOrigin}
                    disabled={controlsLocked || !connected || !!soleTipLengthError}
                    style={buttonStateStyle(primaryButtonStyle, controlsLocked || !connected || !!soleTipLengthError)}
                  >
                    Set origin
                  </button>
                </div>
              </div>
            )}

            {isMulti && step === 2 && (
              <div>
                <h3 style={sectionTitleStyle}>Set XY Origin</h3>
                <p style={instructionStyle}>
                  Put the calibration block at the front-left corner of the deck. Jog the selected leftmost instrument until it is directly over the mark on the block, then continue.
                </p>
                {referenceInstrumentIsPipette && (
                  <div style={noteStyle}>
                    {referenceTipAttached
                      ? `Using ${selectedReference} with a ${tipLengths[selectedReference]} mm tip (set in Prepare).`
                      : `Using ${selectedReference} bare nozzle (set in Prepare).`}
                  </div>
                )}
                <JogPanel
                  xyStep={xyStep}
                  zStep={zStep}
                  setXyStep={setXyStep}
                  setZStep={setZStep}
                  disabled={!connected || busy || homing || !!alarmRecoveryMessage}
                  alarmed={!!alarmRecoveryMessage}
                  onStartJog={startJog}
                  onStopJog={releaseJog}
                />
                <div style={actionRowStyle}>
                  <button onClick={setXY} disabled={controlsLocked || !connected || !!referenceTipLengthError} style={buttonStateStyle(primaryButtonStyle, controlsLocked || !connected || !!referenceTipLengthError)}>Set XY origin and continue</button>
                </div>
              </div>
            )}

            {isMulti && step === 3 && (
              <div>
                <h3 style={sectionTitleStyle}>Calibration Block Height</h3>
                <p style={instructionStyle}>
                  Enter the height of the calibration block above the deck.
                </p>
                <div style={fieldRowStyle}>
                  <label style={fieldStyle}>
                    <span style={labelStyle}>Block height (mm)</span>
                    <input
                      value={blockHeight}
                      onChange={(event) => setBlockHeight(event.target.value)}
                      style={inputStyle}
                      inputMode="decimal"
                      autoFocus
                    />
                  </label>
                </div>
                <div style={actionRowStyle}>
                  <button onClick={() => continueFromBlockHeight(4)} disabled={controlsLocked} style={buttonStateStyle(primaryButtonStyle, controlsLocked)}>Continue</button>
                </div>
              </div>
            )}

            {isMulti && step === 4 && (
              <div>
                <h3 style={sectionTitleStyle}>Set Z Reference</h3>
                <p style={instructionStyle}>
                  Keep the block where it is. Jog {selectedLowest || "the lowest instrument"} until it just touches the top of the block, then continue.
                </p>
                {lowestInstrumentIsPipette && (
                  <CalibrationTipControls attached={lowestTipAttached} length={tipLengths[selectedLowest] ?? ""}
                    disabled={controlsLocked} error={lowestTipLengthError}
                    onAttachedChange={(attached) => setTipAttached((prev) => ({ ...prev, [selectedLowest]: attached }))}
                    onLengthChange={(length) => setTipLengths((prev) => ({ ...prev, [selectedLowest]: length }))} />
                )}
                <JogPanel
                  xyStep={xyStep}
                  zStep={zStep}
                  setXyStep={setXyStep}
                  setZStep={setZStep}
                  disabled={!connected || busy || homing || !!alarmRecoveryMessage}
                  alarmed={!!alarmRecoveryMessage}
                  onStartJog={startJog}
                  onStopJog={releaseJog}
                />
                <div style={actionRowStyle}>
                  <button
                    onClick={setZ}
                    disabled={controlsLocked || !connected || !xyOrigin || !!lowestTipLengthError}
                    style={buttonStateStyle(primaryButtonStyle, controlsLocked || !connected || !xyOrigin || !!lowestTipLengthError)}
                  >
                    {`Set Z reference with ${selectedLowest} and continue`}
                  </button>
                </div>
              </div>
            )}

            {isMulti && step === 5 && (
              <div>
                <h3 style={sectionTitleStyle}>Record Instruments</h3>
                <p style={instructionStyle}>
                  Keep the block where it is. Jog each instrument until it just touches the top of the block, then record it.
                </p>
                <div style={instrumentListStyle}>
                  {calibratableInstruments.map((name) => (
                    <div key={name} style={instrumentRowStyle}>
                      <strong>{name}</strong>
                      <span style={{ ...theme.mono, color: theme.color.textMuted }}>
                        {instrumentPositions[name]
                          ? "recorded"
                          : name === nextInstrumentToRecord
                            ? "up next"
                            : "pending"}
                      </span>
                    </div>
                  ))}
                </div>
                {followCameraInstruments.length > 0 && (
                  <p style={instructionStyle}>
                    {followCameraInstruments.join(", ")}: calibrated automatically with the camera.
                  </p>
                )}
                {nextInstrumentToRecord ? (
                  <div style={activeInstrumentStyle}>
                    <div style={{ marginBottom: 10 }}>
                      <span style={labelStyle}>Active instrument</span>
                      <h4 style={{ margin: "2px 0 0", fontSize: 15, color: theme.color.ink }}>{nextInstrumentToRecord}</h4>
                      {nextInstrumentIsCamera && (
                        <p style={{ ...instructionStyle, margin: "8px 0 0" }}>
                          Center the camera over the calibration block mark, then enter the distance from the camera to the top of the block.
                        </p>
                      )}
                    </div>
                    {nextInstrumentIsCamera && (
                      <CameraPreview key={nextInstrumentToRecord} instrument={nextInstrumentToRecord} />
                    )}
                    {nextInstrumentIsCamera && (
                      <label style={{ ...fieldStyle, marginBottom: 12 }}>
                        <span style={labelStyle}>Distance from calibration block (mm)</span>
                        <input
                          aria-label="Distance from calibration block (mm)"
                          value={cameraBlockDistances[nextInstrumentToRecord] ?? ""}
                          onChange={(event) => setCameraBlockDistances((prev) => ({
                            ...prev,
                            [nextInstrumentToRecord]: event.target.value,
                          }))}
                          disabled={controlsLocked}
                          inputMode="decimal"
                          style={buttonStateStyle(inputStyle, controlsLocked)}
                        />
                        {nextCameraDistanceError && (
                          <span style={{ color: theme.color.danger, fontSize: 12 }}>{nextCameraDistanceError}</span>
                        )}
                      </label>
                    )}
                    {nextInstrumentIsPipette && (
                      <CalibrationTipControls attached={nextInstrumentTipAttached} length={tipLengths[nextInstrumentToRecord] ?? ""}
                        disabled={controlsLocked} error={nextTipLengthError}
                        onAttachedChange={(attached) => setTipAttached((prev) => ({ ...prev, [nextInstrumentToRecord]: attached }))}
                        onLengthChange={(length) => setTipLengths((prev) => ({ ...prev, [nextInstrumentToRecord]: length }))} />
                    )}
                    <JogPanel
                      xyStep={xyStep}
                      zStep={zStep}
                      setXyStep={setXyStep}
                      setZStep={setZStep}
                      disabled={!connected || busy || homing || !!alarmRecoveryMessage}
                      alarmed={!!alarmRecoveryMessage}
                      onStartJog={startJog}
                      onStopJog={releaseJog}
                    />
                    <div style={actionRowStyle}>
                      <button
                        onClick={() => recordCurrentInstrument(nextInstrumentToRecord)}
                        disabled={controlsLocked || !connected || !!nextCameraDistanceError || !!nextTipLengthError}
                        style={buttonStateStyle(primaryButtonStyle, controlsLocked || !connected || !!nextCameraDistanceError || !!nextTipLengthError)}
                      >
                        {`Record ${nextInstrumentToRecord}`}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={noteStyle}>All instruments recorded. Continue to save.</div>
                )}
              </div>
            )}

            {((!isMulti && step === 4) || (isMulti && step === 6)) && (
              <div>
                <h3 style={sectionTitleStyle}>Save</h3>
                <p style={instructionStyle}>
                  Clear the deck. The gantry will home and measure its travel, then the calibration is saved to {normalizedOutput} and this window closes.
                </p>
                <div style={actionRowStyle}>
                  <button onClick={save} disabled={controlsLocked || !readyForSave} style={buttonStateStyle(primaryButtonStyle, controlsLocked || !readyForSave)}>
                    Save
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function defaultOutputFilename(filename: string): string {
  return filename || "gantry.yaml";
}

function requirePosition(position: GantryPosition): CapturedPosition {
  if (!position.connected) throw new Error("Gantry is not connected.");
  if (isGantryHoming(position.status)) throw new Error("Wait for homing to finish before recording a position.");
  if (![position.work_x, position.work_y, position.work_z].every((value) => typeof value === "number" && Number.isFinite(value))) {
    throw new Error("Work coordinate position is not available. Ensure homing and work coordinate setup completed before recording positions.");
  }
  return {
    x: Number(position.work_x),
    y: Number(position.work_y),
    z: Number(position.work_z),
  };
}

function requireCaptured(value: CapturedPosition | null, label: string): number {
  if (!value || !Number.isFinite(value.z)) {
    throw new Error(`${label} is not available. Home the gantry before recording the block touch.`);
  }
  return value.z;
}

function requireZCalibration(value: ZCalibrationResult | null): ZCalibrationResult {
  if (!value) {
    throw new Error("Z calibration is not available. Set the Z reference before saving.");
  }
  return value;
}

function capturedFromPlain(position: { x: number; y: number; z: number }): CapturedPosition {
  return {
    x: Number(position.x),
    y: Number(position.y),
    z: Number(position.z),
  };
}

function formatOptionalNumber(value: number | null | undefined): string {
  return value == null ? "" : String(value);
}

function parseBlockHeight(value: string): number {
  if (!value.trim()) {
    throw new Error("Enter a calibration reference height before continuing.");
  }
  const height = Number(value);
  if (!Number.isFinite(height) || height <= 0) {
    throw new Error("Calibration reference height must be greater than 0.");
  }
  return roundMm(height);
}

function parseCameraBlockDistance(value: string): number {
  if (!value.trim()) {
    throw new Error("Enter the distance from calibration block before recording camera position.");
  }
  const distance = Number(value);
  if (!Number.isFinite(distance) || distance < 0) {
    throw new Error("Distance from calibration block must be 0 or greater.");
  }
  return roundMm(distance);
}

function validateCameraBlockDistance(value: string | undefined): string | null {
  try {
    parseCameraBlockDistance(value ?? "");
    return null;
  } catch (err) {
    return errorMessage(err);
  }
}

function parsedCameraBlockDistances(
  values: Record<string, string>,
  cameras: string[],
): Record<string, number> {
  const parsed: Record<string, number> = {};
  for (const name of cameras) {
    if (values[name] == null || !values[name].trim()) continue;
    parsed[name] = parseCameraBlockDistance(values[name]);
  }
  return parsed;
}

function parseTipLength(value: string): number {
  if (!value.trim()) {
    throw new Error("Enter the tip length before recording a position calibrated with a tip attached.");
  }
  const length = Number(value);
  if (!Number.isFinite(length) || length <= 0) {
    throw new Error("Tip length must be greater than 0.");
  }
  return roundMm(length);
}

function validateTipLength(value: string | undefined): string | null {
  try {
    parseTipLength(value ?? "");
    return null;
  } catch (err) {
    return errorMessage(err);
  }
}

function parsedTipLengths(
  values: Record<string, string>,
  attached: Record<string, boolean>,
): Record<string, number> {
  const parsed: Record<string, number> = {};
  for (const name of Object.keys(attached)) {
    if (!attached[name]) continue;
    if (values[name] == null || !values[name].trim()) continue;
    parsed[name] = parseTipLength(values[name]);
  }
  return parsed;
}

function roundMm(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function looksLikeAlarm(message: string): boolean {
  return hasGantryAlarm(message);
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function getFocusableElements(root: HTMLElement): HTMLElement[] {
  const selector = [
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "a[href]",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");
  return Array.from(root.querySelectorAll<HTMLElement>(selector))
    .filter((element) => element.getAttribute("aria-hidden") !== "true");
}

function buttonStateStyle(base: React.CSSProperties, disabled: boolean): React.CSSProperties {
  if (!disabled) return base;
  return {
    ...base,
    opacity: 0.45,
    cursor: "not-allowed",
  };
}

function unique(items: string[]): string[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}

function allInstrumentPositionsReady(
  instruments: string[],
  positions: Record<string, CapturedPosition>,
  referenceInstrument: string,
  lowestInstrument: string,
): boolean {
  const required = unique([referenceInstrument, lowestInstrument, ...instruments]);
  return required.length > 0 && required.every((name) => !!positions[name]);
}

function stepLabels(isMulti: boolean): string[] {
  return isMulti
    ? ["Prepare", "Home", "XY origin", "Block height", "Z reference", "Instruments", "Save"]
    : ["Prepare", "Home", "Reference height", "Set origin", "Save"];
}

const overlayStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: theme.chrome.backdrop,
  zIndex: 50,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 24,
};

const modalStyle: React.CSSProperties = {
  width: "min(920px, 96vw)",
  maxHeight: "92vh",
  background: theme.color.surface,
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.lg,
  boxShadow: theme.shadow.overlay,
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 12,
  padding: "16px 18px",
  borderBottom: `1px solid ${theme.color.border}`,
};

const headerActionsStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexShrink: 0,
};

const bodyStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(140px, 170px) minmax(0, 1fr)",
  minHeight: 0,
  overflow: "hidden",
};

const stepsStyle: React.CSSProperties = {
  padding: 12,
  borderRight: `1px solid ${theme.color.border}`,
  background: theme.color.surfaceMuted,
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const contentStyle: React.CSSProperties = {
  padding: 18,
  overflow: "auto",
};

const stepButtonStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  border: "1px solid transparent",
  background: "transparent",
  color: theme.color.textFaint,
  borderRadius: theme.radius.sm,
  padding: "8px 9px",
  fontSize: 12,
  textAlign: "left",
  cursor: "default",
};

const activeStepStyle: React.CSSProperties = {
  ...stepButtonStyle,
  background: theme.color.surface,
  border: `1px solid ${theme.color.accentTintBorder}`,
  color: theme.color.accentText,
  fontWeight: 600,
};

const completedStepStyle: React.CSSProperties = {
  ...stepButtonStyle,
  color: theme.color.successText,
  background: theme.color.successBg,
  border: `1px solid ${theme.color.successBorder}`,
};

const stepNumberStyle: React.CSSProperties = {
  width: 20,
  height: 20,
  borderRadius: "50%",
  background: theme.color.border,
  color: theme.color.ink,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 11,
  flexShrink: 0,
};

const sectionTitleStyle: React.CSSProperties = {
  ...theme.panelTitle,
  margin: "0 0 10px",
  fontSize: 16,
};

const instructionStyle: React.CSSProperties = {
  margin: "0 0 12px",
  color: theme.color.textSecondary,
  fontSize: 13,
  lineHeight: 1.45,
};

const fieldRowStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
  marginBottom: 12,
};

const fieldStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 3,
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  ...theme.fieldLabel,
};

const inputStyle: React.CSSProperties = {
  ...theme.input,
  minWidth: 0,
};

const actionRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  marginTop: 12,
};

const buttonStyle: React.CSSProperties = {
  ...theme.btn.secondary,
  ...theme.btnSmall,
};

const primaryButtonStyle: React.CSSProperties = {
  ...theme.btn.primary,
};

const closeButtonStyle: React.CSSProperties = {
  background: "transparent",
  border: `1px solid ${theme.color.borderStrong}`,
  borderRadius: theme.radius.sm,
  color: theme.color.textMuted,
  cursor: "pointer",
  fontSize: 18,
  lineHeight: 1,
  width: 28,
  height: 28,
};

const errorStyle: React.CSSProperties = {
  ...theme.notice.error,
  marginBottom: 10,
};

const alarmStyle: React.CSSProperties = {
  ...theme.notice.error,
  border: `1px solid ${theme.color.danger}`,
  marginBottom: 10,
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
};

const alarmTitleStyle: React.CSSProperties = {
  color: theme.color.danger,
  fontWeight: 700,
  letterSpacing: "0.04em",
};

const alarmButtonStyle: React.CSSProperties = {
  ...theme.btn.danger,
  ...theme.btnSmall,
  marginLeft: "auto",
};

const noteStyle: React.CSSProperties = {
  ...theme.notice.info,
  marginBottom: 10,
};

const noInstrumentsStyle: React.CSSProperties = {
  ...theme.notice.warning,
  marginBottom: 10,
};

const busyStyle: React.CSSProperties = {
  ...theme.notice.warning,
  marginBottom: 10,
};

const instrumentListStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 8,
  marginBottom: 12,
};

const instrumentRowStyle: React.CSSProperties = {
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.sm,
  padding: "7px 9px",
  display: "flex",
  justifyContent: "space-between",
  gap: 8,
  fontSize: 12,
  color: theme.color.text,
};

const activeInstrumentStyle: React.CSSProperties = {
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.md,
  padding: 12,
  background: theme.color.surfaceMuted,
};
