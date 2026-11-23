import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationWizard from "../../../../src/components/gantry/CalibrationWizard";
import type { GantryPosition, GantryResponse } from "../../../../src/types";

const setupConfirmation = "Same tool, tip, block and fixtures since Home.";
const clearanceConfirmation = "Current hover and recorded path from Home are clear.";
const returnConfirmation = "Same tool, tip, block and fixtures; recorded path from Home is still clear.";
const pose = (status = "Idle"): GantryPosition => ({ x: 10, y: 10, z: -20, work_x: 10, work_y: 10, work_z: -20,
  status, connected: true, calibration_active: true });
const homed = (): GantryPosition => ({ ...pose(), z: 0, work_z: 0 });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}
function configuration(multi = false): GantryResponse {
  return { filename: "gantry.yaml", config: {
    serial_port: "/dev/offline", gantry_type: "cub_xl", cnc: { factory_z_travel_mm: 110, calibration_block_height_mm: 13 },
    working_volume: { x_min: 0, x_max: 400, y_min: 0, y_max: 300, z_min: 0, z_max: 110 },
    instruments: multi ? {
      asmi: { type: "asmi", vendor: "vernier", offset_x: 0, offset_y: 0, depth: 0 },
      pipette: { type: "pipette", vendor: "sartorius", offset_x: 0, offset_y: 0, depth: 0 },
    } : { pipette: { type: "pipette", vendor: "sartorius", offset_x: 0, offset_y: 0, depth: 0 } },
  } };
}
function network() {
  const state = { posts: [] as Array<{ path: string; body: Record<string, unknown> }>, trip: false, id: "",
    hoverAvailable: true, homeStatus: "Idle", pendingHome: null as Promise<Response> | null,
    pendingRecord: null as Promise<Response> | null, pendingReturn: null as Promise<Response> | null,
    records: 0 };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
    if (init?.method === "POST") state.posts.push({ path, body });
    if (path.endsWith("/jog-blocking")) {
      state.id = String(body.jog_id);
      return state.trip ? json({ detail: "ALARM:1 hard limit" }, 409) : json(pose());
    }
    if (path.endsWith("/recovery-context")) return json({ raw_status: state.trip ? "ALARM:1; Pn:Z" : "Idle",
      active_limit_axes: state.trip ? ["z"] : [], failed_jog_id: state.id, eligible: state.trip,
      failed_jog_delta: { x: 0, y: 0, z: -0.5 }, pull_off_delta: { x: 0, y: 0, z: 5 }, manual_available: false });
    if (path.endsWith("/recover-limit")) {
      state.trip = false;
      return json({ status: "recovered", mode: "known_jog", attempts: 1,
        pull_off: { x: 0, y: 0, z: 5 }, commanded_delta: { x: 0, y: 0, z: 5 }, failed_delta: { x: 0, y: 0, z: -0.5 }, messages: [] });
    }
    if (path.endsWith("/prepare-origin")) return json(homed());
    if (path.endsWith("/home-resume")) return state.pendingHome ?? json({ position: { ...homed(), status: state.homeStatus },
      hover_available: !!body.token && state.hoverAvailable, blocked_reason: body.token && !state.hoverAvailable ? "Recorded path could not be verified." : null });
    if (path.endsWith("/home-and-center")) return json({ xy_bounds: { x: 400, y: 300, z: 0 }, position: { x: 200, y: 150, z: 0 } });
    if (path.endsWith("/hover")) {
      state.records += 1;
      return state.pendingRecord ?? json({ token: `hover-${state.records}`, position: pose() });
    }
    if (path.endsWith("/return-hover")) return state.pendingReturn ?? json({ position: pose() });
    if (path.endsWith("/work-coordinates")) return json({ ...pose(), z: 13, work_z: 13 });
    return json(pose());
  }));
  return state;
}
type State = ReturnType<typeof network>;
const posts = (state: State, suffix: string) => state.posts.filter((entry) => entry.path.endsWith(suffix));
function view(gantry = configuration(), open = true, status = "Idle") {
  return <CalibrationWizard open={open} onClose={() => undefined} gantry={gantry} position={pose(status)} onSaveCalibrated={async () => undefined} />;
}
async function enter(user: ReturnType<typeof userEvent.setup>) {
  const output = screen.getByLabelText("Output YAML");
  await user.clear(output); await user.type(output, "measured.yaml");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Home gantry" }));
  const height = await screen.findByLabelText("Reference height (mm)");
  await user.clear(height); await user.type(height, "13");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Measured length (mm)"), "70");
}
async function teachHover(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTitle("X+"));
  await user.click(screen.getByTitle("Y+"));
  await user.click(screen.getByText("Recorded block hover"));
  await user.click(screen.getByRole("checkbox", { name: setupConfirmation }));
  await user.click(screen.getByRole("checkbox", { name: clearanceConfirmation }));
  await user.click(screen.getByRole("button", { name: "Record block hover" }));
}
async function recover(state: State, user: ReturnType<typeof userEvent.setup>) {
  state.trip = true;
  await user.click(screen.getByTitle("Z-"));
  return screen.findByRole("button", { name: "Home and resume" });
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Home and resume calibration", () => {
  it("resumes single-tool Set Origin with settings retained and no implicit capture or return", async () => {
    const state = network(); const user = userEvent.setup();
    render(view()); await enter(user);
    await user.click(await recover(state, user));
    expect(await screen.findByRole("heading", { name: "Set Origin" })).toBeInTheDocument();
    expect(screen.getByLabelText("Tip attached")).toBeChecked();
    expect(screen.getByLabelText("Measured length (mm)")).toHaveValue("70");
    expect(posts(state, "/home-resume")[0].body).toEqual({});
    expect(posts(state, "/work-coordinates")).toHaveLength(0);
    expect(posts(state, "/return-hover")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Set origin" }));
    expect(await screen.findByText(/saved to measured.yaml/)).toBeInTheDocument();
    expect(posts(state, "/work-coordinates")[0].body).toEqual({ x: 0, y: 0, z: 13 });
  });

  it("invalidates an already captured origin before resuming Set Origin", async () => {
    const state = network(); const user = userEvent.setup();
    const { rerender } = render(view()); await enter(user);
    await user.click(screen.getByRole("button", { name: "Set origin" }));
    await screen.findByRole("button", { name: "Save" });
    rerender(view(configuration(), true, "Home required"));
    await user.click(await screen.findByRole("button", { name: "Home and resume" }));
    expect(await screen.findByRole("heading", { name: "Set Origin" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(posts(state, "/work-coordinates")).toHaveLength(1);
  });

  it("reacquires multi-tool XY before Z, preserves tool choices and block height, and states the block handoff", async () => {
    const state = network(); const user = userEvent.setup();
    render(view(configuration(true)));
    await user.selectOptions(screen.getByLabelText("Lowest instrument"), "pipette");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));
    await user.click(screen.getByRole("button", { name: "Set XY origin and continue" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByLabelText("Measured length (mm)"), "70");
    await user.click(await recover(state, user));
    expect(await screen.findByRole("heading", { name: "Set XY Origin" })).toBeInTheDocument();
    expect(screen.getByText(/front-left corner of the deck/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Set XY origin and continue" }));
    expect(await screen.findByText(/Place the calibration block at the center mark/)).toBeInTheDocument();
    expect(screen.getByLabelText("Block height (mm)")).toHaveValue("13");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByLabelText("Measured length (mm)")).toHaveValue("70");
    expect(screen.getByRole("button", { name: "Set Z reference with pipette and continue" })).toBeEnabled();
    expect(screen.queryByText("Recorded block hover")).not.toBeInTheDocument();
  });

  it("records only a completed owned route and requires renewed confirmation before a separate return", async () => {
    const state = network(); const user = userEvent.setup();
    render(view()); await enter(user);
    await user.click(screen.getByText("Recorded block hover"));
    expect(screen.getByRole("button", { name: "Record block hover" })).toBeDisabled();
    await user.click(screen.getByText("Recorded block hover"));
    await teachHover(user);
    await screen.findByText("Block hover recorded.");
    const ids = posts(state, "/jog-blocking").map((entry) => entry.body.jog_id);
    expect(posts(state, "/hover")[0].body).toEqual({ instrument: "pipette", tip_attached: true, tip_length_mm: 70,
      block_height_mm: 13, jog_ids: ids, fixture_confirmed: true, clearance_confirmed: true, path_clear: true });
    await user.click(await recover(state, user));
    const action = await screen.findByRole("button", { name: "Return above block" });
    expect(action).toBeDisabled();
    expect(posts(state, "/return-hover")).toHaveLength(0);
    await user.click(screen.getByRole("checkbox", { name: returnConfirmation }));
    await user.click(action);
    expect(await screen.findByText("Above block. Make the final touch manually.")).toBeInTheDocument();
    expect(posts(state, "/return-hover")[0].body).toEqual({ token: "hover-1", instrument: "pipette", tip_attached: true,
      tip_length_mm: 70, block_height_mm: 13, setup_unchanged: true, path_clear: true });
    expect(posts(state, "/work-coordinates")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("revokes the recorded hover when tip settings change without losing the measured settings", async () => {
    const state = network(); const user = userEvent.setup();
    render(view()); await enter(user); await teachHover(user);
    await screen.findByText("Block hover recorded.");
    const length = screen.getByLabelText("Measured length (mm)");
    await user.clear(length); await user.type(length, "71");
    await waitFor(() => expect(posts(state, "/hover/cancel")[0].body).toEqual({ token: "hover-1" }));
    await user.click(await recover(state, user));
    expect(screen.getByLabelText("Measured length (mm)")).toHaveValue("71");
    expect(posts(state, "/home-resume")[0].body).toEqual({});
    expect(screen.queryByRole("button", { name: "Return above block" })).not.toBeInTheDocument();
  });

  it("keeps manual resume usable when the server cannot reverify a stored route", async () => {
    const state = network(); state.hoverAvailable = false; const user = userEvent.setup();
    render(view()); await enter(user); await teachHover(user);
    await screen.findByText("Block hover recorded.");
    await user.click(await recover(state, user));
    expect(await screen.findByText(/Recorded path could not be verified/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set origin" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Return above block" })).not.toBeInTheDocument();
    expect(posts(state, "/return-hover")).toHaveLength(0);
  });

  it("requires fresh clearance confirmation after jogging and withdraws return after leaving Home", async () => {
    const state = network(); const user = userEvent.setup();
    render(view()); await enter(user);
    await user.click(screen.getByTitle("X+"));
    await user.click(screen.getByText("Recorded block hover"));
    await user.click(screen.getByRole("checkbox", { name: setupConfirmation }));
    await user.click(screen.getByRole("checkbox", { name: clearanceConfirmation }));
    await user.click(screen.getByTitle("Y+"));
    expect(screen.getByRole("checkbox", { name: clearanceConfirmation })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Record block hover" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: clearanceConfirmation }));
    await user.click(screen.getByRole("button", { name: "Record block hover" }));
    await screen.findByText("Block hover recorded.");
    await user.click(await recover(state, user));
    await user.click(screen.getByRole("checkbox", { name: returnConfirmation }));
    await user.click(screen.getByTitle("Y+"));
    expect(screen.queryByRole("button", { name: "Return above block" })).not.toBeInTheDocument();
    expect(posts(state, "/return-hover")).toHaveLength(0);
  });

  it("revokes a late old record token without clearing a reopened wizard's new checkpoint", async () => {
    const state = network(); const old = deferred(); state.pendingRecord = old.promise;
    const user = userEvent.setup();
    const { rerender } = render(view()); await enter(user); await teachHover(user);
    rerender(view(configuration(), false)); rerender(view());
    state.pendingRecord = null;
    await enter(user); await teachHover(user);
    await screen.findByText("Block hover recorded.");
    await act(async () => old.resolve(json({ token: "old-record", position: pose() })));
    expect(posts(state, "/hover/cancel").map((entry) => entry.body)).toEqual([{ token: "old-record" }]);
    await user.click(await recover(state, user));
    expect(posts(state, "/home-resume")[0].body).toEqual({ token: "hover-2" });
    expect(await screen.findByRole("button", { name: "Return above block" })).toBeInTheDocument();
  });

  it("keeps captures blocked when recovery Home does not verify Idle", async () => {
    const state = network(); state.homeStatus = "Run";
    const user = userEvent.setup();
    render(view()); await enter(user);
    await user.click(await recover(state, user));
    expect(await screen.findByText("Homing is unverified: Run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set origin" })).toBeDisabled();
    expect(screen.queryByText("Homed.")).not.toBeInTheDocument();
    expect(posts(state, "/return-hover")).toHaveLength(0);
    expect(posts(state, "/work-coordinates")).toHaveLength(0);
  });

  it("cancels a pending return and ignores its late success", async () => {
    const state = network(); const pending = deferred(); state.pendingReturn = pending.promise;
    const user = userEvent.setup();
    render(view()); await enter(user); await teachHover(user);
    await screen.findByText("Block hover recorded.");
    await user.click(await recover(state, user));
    await user.click(screen.getByRole("checkbox", { name: returnConfirmation }));
    await user.click(screen.getByRole("button", { name: "Return above block" }));
    await user.click(await screen.findByRole("button", { name: "Stop return" }));
    await act(async () => pending.resolve(json({ position: pose() })));
    expect(screen.getByText("Return cancelled. Reapproach manually.")).toBeInTheDocument();
    expect(screen.queryByText("Above block. Make the final touch manually.")).not.toBeInTheDocument();
    expect(posts(state, "/jog-cancel")).toHaveLength(1);
    expect(posts(state, "/return-hover")).toHaveLength(1);
    expect(posts(state, "/work-coordinates")).toHaveLength(0);
  });

  it("sends one Home for repeated activation and ignores completion after closing/reopening", async () => {
    const state = network(); const pending = deferred(); state.pendingHome = pending.promise;
    const user = userEvent.setup();
    const { rerender } = render(view()); await enter(user);
    const home = await recover(state, user);
    act(() => { home.click(); home.click(); });
    expect(posts(state, "/home-resume")).toHaveLength(1);
    rerender(view(configuration(), false)); rerender(view());
    await enter(user);
    await act(async () => pending.resolve(json({ position: homed(), hover_available: true, blocked_reason: null })));
    expect(screen.getByRole("heading", { name: "Set Origin" })).toBeInTheDocument();
    expect(screen.queryByText("Homed.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Return above block" })).not.toBeInTheDocument();
  });
});
