import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationWizard from "../../../../src/components/gantry/CalibrationWizard";
import LabwareCalibrationModal from "../../../../src/components/deck/LabwareCalibrationModal";
import type { DeckResponse, GantryPosition, GantryResponse } from "../../../../src/types";
import type { LimitRecoveryContext } from "../../../../src/api/client";

type Mode = "gantry" | "labware";
const gantry: GantryResponse = {
  filename: "gantry.yaml", config: {
    serial_port: "/dev/offline", gantry_type: "cub_xl", cnc: { factory_z_travel_mm: 110, calibration_block_height_mm: 35 },
    working_volume: { x_min: 0, x_max: 400, y_min: 0, y_max: 400, z_min: 0, z_max: 110 }, grbl_settings: {},
    instruments: { asmi: { type: "asmi", vendor: "vernier", offset_x: 0, offset_y: 0, depth: 0 } },
  },
};
const deck: DeckResponse = { filename: "deck.yaml", labware: [{ key: "tips", wells: null, config: {
  type: "tip_rack", name: "Tips", model_name: "demo", rows: 2, columns: 2, x_offset: 9, y_offset: 9,
  calibration: { a1: { x: 0, y: 0, z: 20 }, a2: { x: 9, y: 0, z: 20 } }, pickup_z: 20, drop_z: 30, tip_length: 50,
} }] };
function position(status = "Idle"): GantryPosition { return { x: 0, y: 0, z: 20, work_x: 0, work_y: 0, work_z: 20, connected: true, status, calibration_active: false }; }
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}
function recoveryResult() { return { status: "recovered", mode: "known_jog", attempts: 1, pull_off: { x: 0, y: -5, z: 0 }, commanded_delta: { x: 0, y: -5, z: 0 }, failed_delta: { x: 0, y: 0.5, z: 0 }, messages: [] }; }

function network() {
  const state = {
    id: null as string | null,
    idOverride: undefined as string | null | undefined,
    jogStatus: 409,
    jogMessage: "ALARM:1 hard limit",
    recoveryStatus: 200,
    pendingRecovery: null as Promise<Response> | null,
    pendingHome: null as Promise<Response> | null,
    pendingPosition: null as Promise<Response> | null,
    pendingJog: null as Promise<Response> | null,
    pendingCancel: null as Promise<Response> | null,
    readPosition: position(),
    contextOverrides: {} as Partial<LimitRecoveryContext>,
    contextReads: 0,
    contextFailures: 0,
    posts: [] as Array<{ path: string; body: Record<string, unknown> }>,
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method === "POST") {
      const body = init.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
      state.posts.push({ path, body });
      if (path.endsWith("/jog") || path.endsWith("/jog-blocking")) {
        state.id = typeof body.jog_id === "string" ? body.jog_id : null;
        if (state.pendingJog) return state.pendingJog;
        return state.jogStatus === 200 ? json(position()) : json({ detail: state.jogMessage }, state.jogStatus);
      }
      if (path.endsWith("/recover-limit")) return state.pendingRecovery ?? json(state.recoveryStatus === 200 ? recoveryResult() : { detail: "Recovery failed." }, state.recoveryStatus);
      if (path.endsWith("/jog-cancel") && state.pendingCancel) return state.pendingCancel;
      if (path.endsWith("/prepare-origin") && state.pendingHome) return state.pendingHome;
    }
    if (path.endsWith("/position")) return state.pendingPosition ?? json(state.readPosition);
    if (path.endsWith("/home-and-center")) return json({ xy_bounds: { x: 100, y: 100, z: 20 }, position: { x: 50, y: 50, z: 20 } });
    if (path.endsWith("/recovery-context")) {
      state.contextReads += 1;
      if (state.contextFailures > 0) { state.contextFailures -= 1; throw new TypeError("context unavailable"); }
      return json({
      raw_status: "ALARM:1; Pn:Y", active_limit_axes: ["y"], failed_jog_id: state.idOverride === undefined ? state.id : state.idOverride,
      failed_jog_delta: { x: 0, y: 0.5, z: 0 }, eligible: true, blocked_reason: null,
      pull_off_delta: { x: 0, y: -5, z: 0 }, manual_available: true, ...state.contextOverrides,
      });
    }
    return json(position());
  }));
  return state;
}
function view(mode: Mode, status: string, open = true, config = gantry, connected = true) {
  const pose = { ...position(status), connected };
  return mode === "gantry"
    ? <CalibrationWizard open={open} onClose={() => undefined} gantry={config} position={pose} onSaveCalibrated={async () => undefined} />
    : <LabwareCalibrationModal open={open} onClose={() => undefined} gantry={config} deck={deck} position={pose} onSaveDeck={async () => undefined} />;
}
async function enter(mode: Mode, user: ReturnType<typeof userEvent.setup>) {
  if (mode === "gantry") {
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));
    await user.click(await screen.findByRole("button", { name: "Continue" }));
  } else {
    await user.selectOptions(screen.getByLabelText("Labware type"), "tip_rack");
    await user.click(screen.getByRole("button", { name: "Continue" }));
  }
}
const jogs = (state: ReturnType<typeof network>) => state.posts.filter((entry) => /\/jog(?:-blocking)?$/.test(entry.path));
const recoveryFallback = async (mode: Mode, state: ReturnType<typeof network>, reads = 1) => {
  if (mode === "gantry") {
    await waitFor(() => expect(state.contextReads).toBeGreaterThanOrEqual(reads), { timeout: 2000 });
    await act(async () => undefined);
  } else await screen.findByText("Manual recovery", {}, { timeout: 2000 });
  if (mode === "gantry") {
    expect(screen.queryByText("Manual recovery")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pull off|Unlock alarm|Home and resume/ })).not.toBeInTheDocument();
  }
};
const recoveries = (state: ReturnType<typeof network>) => state.posts.filter((entry) => entry.path.endsWith("/recover-limit"));
const waitForRecovery = (mode: Mode) => mode === "gantry"
  ? screen.findByText("Recovering… Space to cancel.")
  : screen.findByRole("button", { name: "Stop recovery" });
async function cancelRecovery(mode: Mode, user: ReturnType<typeof userEvent.setup>) {
  await waitForRecovery(mode);
  if (mode === "gantry") fireEvent.keyDown(window, { key: " " });
  else await user.click(screen.getByRole("button", { name: "Stop recovery" }));
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe.each<Mode>(["gantry", "labware"])("%s automatic calibration backoff", (mode) => {
  it("POSTs automatically for its own correlated jog error without a recovery click", async () => {
    const state = network();
    const user = userEvent.setup();
    render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    await waitFor(() => expect(recoveries(state)).toHaveLength(1));
    expect(state.id).toMatch(/^calibration-/);
    expect(recoveries(state)[0].body).toEqual({ x: 0, y: 0.5, z: 0, jog_id: state.id });
    expect(await screen.findByText(/Home required/i)).toBeInTheDocument();
    expect(state.posts.filter((entry) => entry.path.endsWith("/jog-cancel"))).toHaveLength(0);
    expect(state.posts.some((entry) => entry.path.endsWith("/home") || entry.path.endsWith("/reset-unlock"))).toBe(false);
  });

  it("automatically handles a polling fault once and does not resume the held jog", async () => {
    const state = network(); state.jogStatus = 200;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await waitFor(() => expect(recoveries(state)).toHaveLength(1));
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1100)); });
    expect(recoveries(state)).toHaveLength(1);
    expect(jogs(state)).toHaveLength(1);
  });

  it("halts a repeated held jog locally before automatic recovery without revoking its ID", async () => {
    const state = network(); state.jogStatus = 200;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    fireEvent.mouseDown(screen.getByTitle("Y+"));
    await waitFor(() => expect(jogs(state).length).toBeGreaterThanOrEqual(2));
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await waitFor(() => expect(recoveries(state)).toHaveLength(1));
    const count = jogs(state).length;
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 350)); });
    expect(jogs(state)).toHaveLength(count);
    expect(state.posts.some((entry) => entry.path.endsWith("/jog-cancel"))).toBe(false);
  });

  it.each(["foreign", "missing", "wrong-pin", "multiple-pins", "missing-pins"])("does not auto-recover %s context", async (kind) => {
    const state = network();
    if (kind === "foreign") state.idOverride = "other-client-jog";
    if (kind === "missing") state.idOverride = null;
    if (kind === "wrong-pin") state.contextOverrides = { eligible: false, active_limit_axes: ["x"], pull_off_delta: null };
    if (kind === "multiple-pins") state.contextOverrides = { eligible: false, active_limit_axes: ["x", "y"], pull_off_delta: null };
    if (kind === "missing-pins") state.contextOverrides = { eligible: false, active_limit_axes: [], pull_off_delta: null };
    const user = userEvent.setup();
    render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    await waitFor(() => expect(state.contextReads).toBeGreaterThan(0));
    await act(async () => undefined);
    expect(recoveries(state)).toHaveLength(0);
  });

  it("does not recover an alarm already present when opening", async () => {
    const state = network(); state.idOverride = "old-wizard-jog";
    render(view(mode, "ALARM:1; Pn:Y"));
    await recoveryFallback(mode, state);
    expect(recoveries(state)).toHaveLength(0);
  });

  it("does not retry a failed attempt when recovery controls remount", async () => {
    const state = network(); state.recoveryStatus = 409;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    await screen.findByText("Recovery failed.");
    rerender(view(mode, "Home required"));
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await recoveryFallback(mode, state);
    expect(recoveries(state)).toHaveLength(1);
  });

  it("revokes ownership on Stop and does not retry on a later poll", async () => {
    const state = network(); const pending = deferred(); state.pendingRecovery = pending.promise;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    await cancelRecovery(mode, user);
    await act(async () => pending.resolve(json(recoveryResult())));
    await screen.findByText(/Recovery stopped/);
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1100)); });
    expect(recoveries(state)).toHaveLength(1);
    expect(state.posts.some((entry) => entry.path.endsWith("/jog-cancel"))).toBe(true);
  });

  it("does not adopt the previous wizard's ID after close/reopen", async () => {
    const state = network(); state.jogStatus = 200;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    expect(state.id).toBeTruthy();
    rerender(view(mode, "Idle", false));
    rerender(view(mode, "ALARM:1; Pn:Y", true));
    await recoveryFallback(mode, state);
    expect(recoveries(state)).toHaveLength(0);
  });

  it("ignores late recovery completion after close/reopen while a new action is busy", async () => {
    const state = network(); const recovery = deferred(); state.pendingRecovery = recovery.promise;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    await waitForRecovery(mode);
    rerender(view(mode, "Idle", false));
    rerender(view(mode, "Idle", true));
    const current = deferred();
    if (mode === "gantry") {
      state.pendingHome = current.promise;
      await user.click(screen.getByRole("button", { name: "Continue" }));
      await user.click(screen.getByRole("button", { name: "Home gantry" }));
    } else {
      state.pendingPosition = current.promise;
      await enter(mode, user);
      await user.click(screen.getByRole("button", { name: "Record A1" }));
    }
    await act(async () => recovery.resolve(json(recoveryResult())));
    expect(screen.queryByText("Pull-off complete.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: mode === "gantry" ? "Home gantry" : "Record A1" })).toBeDisabled();
    await act(async () => current.resolve(json(position())));
    const cancels = state.posts.filter((entry) => entry.path.endsWith("/jog-cancel")).length;
    await user.click(screen.getByRole("button", { name: mode === "gantry" ? "Close calibration" : "Close labware calibration" }));
    expect(state.posts.filter((entry) => entry.path.endsWith("/jog-cancel"))).toHaveLength(cancels);
  });

  it("does not auto-recover Home required even with an owned ID", async () => {
    const state = network(); state.jogStatus = 200;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    rerender(view(mode, "Home required"));
    await act(async () => undefined);
    expect(recoveries(state)).toHaveLength(0);
  });

  it("ignores a late old Stop failure after reopening while a new action is pending", async () => {
    const state = network(); const recovery = deferred(); const cancel = deferred();
    state.pendingRecovery = recovery.promise; state.pendingCancel = cancel.promise;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    await cancelRecovery(mode, user);
    rerender(view(mode, "Idle", false)); rerender(view(mode, "Idle"));
    const current = deferred();
    if (mode === "gantry") {
      state.pendingHome = current.promise;
      await user.click(screen.getByRole("button", { name: "Continue" }));
      await user.click(screen.getByRole("button", { name: "Home gantry" }));
    } else {
      state.pendingPosition = current.promise;
      await enter(mode, user);
      await user.click(screen.getByRole("button", { name: "Record A1" }));
    }
    await act(async () => {
      cancel.resolve(json({ detail: "Old Stop failed." }, 503));
      recovery.resolve(json(recoveryResult()));
    });
    expect(screen.queryByText("Old Stop failed.")).not.toBeInTheDocument();
    await act(async () => current.resolve(json(position())));
    expect(screen.getByRole("button", { name: mode === "gantry" ? "Continue" : "Record A2" })).toBeEnabled();
  });

  it("does not recover after an uncertain transport rejection even if a matching context arrives", async () => {
    const state = network(); state.jogStatus = 503; state.jogMessage = "Connection lost before acceptance could verify.";
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await recoveryFallback(mode, state);
    expect(recoveries(state)).toHaveLength(0);
  });

  it("revokes an accepted jog when a context read fails and polling later recovers", async () => {
    const state = network(); state.jogStatus = 200; state.contextFailures = 1;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await screen.findByText("context unavailable");
    await recoveryFallback(mode, state, 2);
    expect(recoveries(state)).toHaveLength(0);
  });

  it("revokes an accepted jog on connection loss before any recovery control mounted", async () => {
    const state = network(); state.jogStatus = 200;
    const user = userEvent.setup();
    const { rerender } = render(view(mode, "Idle"));
    await enter(mode, user);
    await user.click(screen.getByTitle("Y+"));
    rerender(view(mode, "Not connected", true, gantry, false));
    rerender(view(mode, "ALARM:1; Pn:Y"));
    await recoveryFallback(mode, state);
    expect(recoveries(state)).toHaveLength(0);
  });
});

async function reachBlockingLift(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Home gantry" }));
  await user.click(await screen.findByRole("button", { name: "Set XY origin and continue" }));
  await user.click(await screen.findByRole("button", { name: "Continue" }));
  await user.click(await screen.findByRole("button", { name: "Set Z reference with asmi and continue" }));
}

describe("blocking calibration lift correlation", () => {
  const multi = { ...gantry, config: { ...gantry.config, instruments: { ...gantry.config.instruments, camera: { type: "camera", vendor: "usb", offset_x: 0, offset_y: 0, depth: 0 } } } };
  it("automatically backs off a post-acceptance blocking-lift fault and stays on its current step", async () => {
    const state = network(); state.readPosition = { ...position(), z: -50, work_z: -50 };
    state.contextOverrides = { active_limit_axes: ["z"], failed_jog_delta: { x: 0, y: 0, z: 15 }, pull_off_delta: { x: 0, y: 0, z: -5 } };
    const user = userEvent.setup();
    render(view("gantry", "Idle", true, multi));
    await reachBlockingLift(user);
    await waitFor(() => expect(recoveries(state)).toHaveLength(1));
    const lift = state.posts.find((entry) => entry.path.endsWith("/jog-blocking"));
    expect(lift?.body.jog_id).toBeTruthy();
    expect(recoveries(state)[0].body).toEqual({ x: 0, y: 0, z: 15, jog_id: lift?.body.jog_id });
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Z reference");
    expect(screen.queryByRole("button", { name: "Record camera" })).not.toBeInTheDocument();
  });

  it("shows a blocking transport failure without attempting recovery", async () => {
    const state = network(); state.jogStatus = 503; state.jogMessage = "Connection lost during blocking lift.";
    state.readPosition = { ...position(), z: -50, work_z: -50 };
    const user = userEvent.setup();
    render(view("gantry", "Idle", true, multi));
    await reachBlockingLift(user);
    expect(await screen.findByText("Connection lost during blocking lift.")).toBeInTheDocument();
    expect(recoveries(state)).toHaveLength(0);
  });

  it("allows verified recovery Home and ignores a late response from the interrupted lift", async () => {
    const state = network(); const lift = deferred(); state.pendingJog = lift.promise;
    state.readPosition = { ...position(), z: -50, work_z: -50 };
    state.contextOverrides = { active_limit_axes: ["z"], failed_jog_delta: { x: 0, y: 0, z: 15 }, pull_off_delta: { x: 0, y: 0, z: -5 } };
    const user = userEvent.setup();
    const { rerender } = render(view("gantry", "Idle", true, multi));
    await reachBlockingLift(user);
    rerender(view("gantry", "ALARM:1; Pn:Z", true, multi));
    await screen.findByText("Home required. Clear the gantry path before homing.");
    state.contextOverrides = { raw_status: "Idle", active_limit_axes: [], eligible: false, pull_off_delta: null };
    rerender(view("gantry", "Home required", true, multi));
    await user.click(await screen.findByRole("button", { name: "Home and restart calibration" }, { timeout: 2000 }));
    await act(async () => lift.resolve(json({ detail: "Old lift fault." }, 409)));
    rerender(view("gantry", "Idle", true, multi));
    expect(await screen.findByRole("heading", { name: "Set XY Origin" })).toBeInTheDocument();
    expect(screen.queryByText("Old lift fault.")).not.toBeInTheDocument();
    expect(screen.queryByText("GANTRY ALARM")).not.toBeInTheDocument();
  });
});

it("invalidates labware captures when its own jog hits a limit", async () => {
  const state = network(); const user = userEvent.setup();
  render(view("labware", "Idle"));
  await enter("labware", user);
  await user.click(screen.getByRole("button", { name: "Record A1" }));
  expect(await screen.findByRole("button", { name: "Record A2" })).toBeEnabled();
  await user.click(screen.getByTitle("Y+"));
  await waitFor(() => expect(recoveries(state)).toHaveLength(1));
  expect(screen.getByRole("button", { name: "Record A1" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Record A2" })).not.toBeInTheDocument();
});

describe("full gantry wizard recovery restart", () => {
  it.each(["Escape", "close", "Space"])("cancels automatic recovery using %s without a transient Stop button", async (method) => {
    const state = network(); const pending = deferred(); state.pendingRecovery = pending.promise;
    const user = userEvent.setup(); const onClose = vi.fn();
    render(<CalibrationWizard open onClose={onClose} gantry={gantry} position={position()} onSaveCalibrated={async () => undefined} />);
    await enter("gantry", user);
    await user.click(screen.getByTitle("Y+"));
    await waitForRecovery("gantry");
    expect(screen.queryByRole("button", { name: "Stop recovery" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close calibration" })).toBeEnabled();
    if (method === "close") await user.click(screen.getByRole("button", { name: "Close calibration" }));
    else {
      const key = method === "Space" ? " " : "Escape";
      fireEvent.keyDown(window, { key });
      fireEvent.keyDown(window, { key, repeat: true });
    }
    await waitFor(() => expect(state.posts.filter((entry) => entry.path.endsWith("/jog-cancel"))).toHaveLength(1));
    if (method === "Space") expect(onClose).not.toHaveBeenCalled();
    else await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    await act(async () => pending.resolve(json(recoveryResult())));
    expect(screen.queryByText("Pull-off complete.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Home and resume" })).not.toBeInTheDocument();
    expect(recoveries(state)).toHaveLength(1);
  });

  it("does not turn Escape or Space into cancellation for unrelated busy homing", async () => {
    const state = network(); const pending = deferred(); state.pendingHome = pending.promise;
    const user = userEvent.setup(); const onClose = vi.fn();
    render(<CalibrationWizard open onClose={onClose} gantry={gantry} position={position()} onSaveCalibrated={async () => undefined} />);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.keyDown(window, { key: " " });
    expect(onClose).not.toHaveBeenCalled();
    expect(state.posts.some((entry) => entry.path.endsWith("/jog-cancel"))).toBe(false);
    await act(async () => pending.resolve(json(position())));
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("does not describe a consumed recovery candidate as an unknown original direction", async () => {
    const state = network(); state.recoveryStatus = 409;
    const user = userEvent.setup();
    render(view("gantry", "Idle")); await enter("gantry", user);
    await user.click(screen.getByTitle("Y+"));
    await screen.findByText("Recovery failed.");
    state.contextOverrides = { eligible: false, failed_jog_id: null, failed_jog_delta: null, pull_off_delta: null,
      blocked_reason: "Original jog direction unknown." };
    await waitFor(() => expect(state.contextReads).toBeGreaterThanOrEqual(2), { timeout: 2000 });
    expect(screen.queryByText("Original jog direction unknown.")).not.toBeInTheDocument();
    expect(screen.queryByText("Recovery attempt ended. Inspect the gantry before continuing.")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("calibration-status-slot")).toHaveLength(1);
    expect(screen.getByText("Recovery failed.")).toBeInTheDocument();
  });

  it("clears the original jog error and requires explicit Home before restarting captures", async () => {
    const state = network();
    const user = userEvent.setup();
    render(view("gantry", "Idle"));
    await enter("gantry", user);
    await user.click(screen.getByTitle("Y+"));
    const home = await screen.findByRole("button", { name: "Home and resume" });
    expect(screen.queryByText("ALARM:1 hard limit")).not.toBeInTheDocument();
    expect(screen.queryByText("Manual recovery")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unlock alarm" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set origin" })).toBeDisabled();
    expect(state.posts.filter((entry) => entry.path.endsWith("/prepare-origin"))).toHaveLength(1);
    await user.click(home);
    expect(await screen.findByText("Homed.")).toBeInTheDocument();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Set origin");
    expect(screen.queryByText("GANTRY ALARM")).not.toBeInTheDocument();
    expect(state.posts.filter((entry) => entry.path.endsWith("/prepare-origin"))).toHaveLength(2);
  });

  it("ignores a late failed jog response after verified pull-off", async () => {
    const state = network();
    const pending = deferred(); state.pendingJog = pending.promise;
    const user = userEvent.setup();
    const { rerender } = render(view("gantry", "Idle"));
    await enter("gantry", user);
    await user.click(screen.getByTitle("Y+"));
    rerender(view("gantry", "ALARM:1; Pn:Y"));
    await screen.findByText("Home required. Clear the gantry path before homing.");
    await act(async () => pending.resolve(json({ detail: "Old jog fault." }, 409)));
    state.contextOverrides = { raw_status: "Idle", active_limit_axes: [], eligible: false, pull_off_delta: null };
    rerender(view("gantry", "Home required"));
    expect(screen.queryByText("Old jog fault.")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Home and resume" }, { timeout: 2000 })).toBeEnabled();
    expect(recoveries(state)).toHaveLength(1);
  });

  it("blocks Home if a poll becomes unverified or moving after local recovery success", async () => {
    network();
    const user = userEvent.setup();
    const { rerender } = render(view("gantry", "Idle"));
    await enter("gantry", user);
    await user.click(screen.getByTitle("Y+"));
    expect(await screen.findByRole("button", { name: "Home and resume" })).toBeEnabled();
    for (const status of ["Query failed", "Unknown", "Run"]) {
      rerender(view("gantry", status));
      expect(screen.queryByRole("button", { name: "Home and resume" })).not.toBeInTheDocument();
    }
    rerender(<CalibrationWizard open onClose={() => undefined} gantry={gantry}
      position={{ ...position(), work_z: null }} onSaveCalibrated={async () => undefined} />);
    expect(screen.queryByRole("button", { name: "Home and resume" })).not.toBeInTheDocument();
  });

  it("keeps rapid presses single-flight and budgets time for a configured slow axis", async () => {
    const state = network();
    const pending = deferred(); state.pendingJog = pending.promise;
    const slow = { ...gantry, config: { ...gantry.config, grbl_settings: { max_rate_y: 100 } } };
    const user = userEvent.setup();
    render(view("gantry", "Idle", true, slow));
    await enter("gantry", user);
    await user.click(within(screen.getByRole("group", { name: "XY jog step (mm)" })).getByRole("button", { name: "50" }));
    expect(jogs(state)).toHaveLength(0);
    await user.click(screen.getByTitle("Y+"));
    await user.click(screen.getByTitle("X+"));
    expect(jogs(state)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Set origin" })).toBeDisabled();
    expect(jogs(state)[0].path).toMatch(/\/jog-blocking$/);
    expect(jogs(state)[0].body.timeout_s).toBe(35);
    await act(async () => pending.resolve(json(position())));
    state.pendingJog = null; state.jogStatus = 200;
    await user.click(screen.getByTitle("X+"));
    expect(jogs(state)).toHaveLength(2);
  });

  it.each(["close", "reset", "unmount"])("cancels one in-flight click on %s without a duplicate cancel", async (action) => {
    const state = network();
    const pending = deferred(); state.pendingJog = pending.promise;
    const user = userEvent.setup();
    const { unmount } = render(view("gantry", "Idle"));
    await enter("gantry", user);
    await user.click(screen.getByTitle("Y+"));
    expect(state.posts.some((entry) => entry.path.endsWith("/jog-cancel"))).toBe(false);
    if (action === "unmount") unmount();
    else await user.click(screen.getByRole("button", { name: action === "close" ? "Close calibration" : "Reset wizard" }));
    unmount();
    expect(state.posts.filter((entry) => entry.path.endsWith("/jog-cancel"))).toHaveLength(1);
    await act(async () => pending.resolve(json({ detail: "Stopped old jog." }, 409)));
    expect(recoveries(state)).toHaveLength(0);
  });

  it("does not let release or key-up cancel automatic recovery, but accepts keyboard Stop", async () => {
    const state = network(); state.jogStatus = 200;
    const pending = deferred(); state.pendingRecovery = pending.promise;
    const user = userEvent.setup();
    const { rerender } = render(view("gantry", "Idle"));
    await enter("gantry", user);
    fireEvent.mouseDown(screen.getByTitle("Y+"));
    await waitFor(() => expect(jogs(state).length).toBeGreaterThanOrEqual(2));
    rerender(view("gantry", "ALARM:1; Pn:Y"));
    await waitForRecovery("gantry");
    expect(screen.queryByRole("button", { name: "Stop recovery" })).not.toBeInTheDocument();
    fireEvent.mouseUp(window);
    fireEvent.keyUp(window, { key: "ArrowUp" });
    expect(state.posts.some((entry) => entry.path.endsWith("/jog-cancel"))).toBe(false);
    fireEvent.keyDown(window, { key: " " });
    await waitFor(() => expect(state.posts.filter((entry) => entry.path.endsWith("/jog-cancel"))).toHaveLength(1));
    expect(state.posts.filter((entry) => entry.path.endsWith("/jog-cancel"))).toHaveLength(1);
    await act(async () => pending.resolve(json(recoveryResult())));
    expect(await screen.findByText(/Recovery stopped/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Home and resume" })).not.toBeInTheDocument();
  });

  it("offers Home for standalone Home required only after fresh clear-pin Idle verification", async () => {
    const state = network();
    state.contextOverrides = { raw_status: "<Idle|WPos:0,0,20>", active_limit_axes: [], eligible: false, failed_jog_delta: null, pull_off_delta: null };
    const user = userEvent.setup();
    render(view("gantry", "Home required"));
    await user.click(await screen.findByRole("button", { name: "Home and resume" }));
    expect(await screen.findByText("Homed.")).toBeInTheDocument();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Reference height");
    expect(recoveries(state)).toHaveLength(0);
  });

  it.each(["live-pin", "transport"])("does not offer Home for unverified %s state", async (kind) => {
    const state = network();
    if (kind === "transport") state.contextFailures = 1;
    render(view("gantry", "Home required"));
    await waitFor(() => expect(state.contextReads).toBe(1));
    await act(async () => undefined);
    expect(screen.queryByRole("button", { name: "Home and resume" })).not.toBeInTheDocument();
    expect(state.posts).toHaveLength(0);
  });
});
