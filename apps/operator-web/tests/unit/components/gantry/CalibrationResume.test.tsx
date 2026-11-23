import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationWizard from "../../../../src/components/gantry/CalibrationWizard";
import type { GantryPosition, GantryResponse } from "../../../../src/types";

const position = (status = "Idle"): GantryPosition => ({ x: 10, y: 10, z: -20, work_x: 10, work_y: 10, work_z: -20,
  status, connected: true, calibration_active: true });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function config(multi = false): GantryResponse {
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
    homeResult: { ...position(), z: 0, work_z: 0 }, pendingHome: null as Promise<Response> | null };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input), body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
    if (init?.method === "POST") state.posts.push({ path, body });
    if (path.endsWith("/prepare-origin")) return state.pendingHome ?? json(state.homeResult);
    if (path.endsWith("/home-and-center")) return json({ xy_bounds: { x: 400, y: 300, z: 0 }, position: { x: 200, y: 150, z: 0 } });
    if (path.endsWith("/jog-blocking")) {
      state.id = String(body.jog_id);
      return state.trip ? json({ detail: "ALARM:1 hard limit" }, 409) : json(position());
    }
    if (path.endsWith("/recovery-context")) return json({ raw_status: state.trip ? "ALARM:1; Pn:Z" : "Idle",
      active_limit_axes: state.trip ? ["z"] : [], failed_jog_id: state.id, eligible: state.trip,
      failed_jog_delta: { x: 0, y: 0, z: -0.5 }, pull_off_delta: { x: 0, y: 0, z: 5 }, manual_available: false });
    if (path.endsWith("/recover-limit")) {
      state.trip = false;
      return json({ status: "recovered", mode: "known_jog", attempts: 1, pull_off: { x: 0, y: 0, z: 5 },
        commanded_delta: { x: 0, y: 0, z: 5 }, failed_delta: { x: 0, y: 0, z: -0.5 }, messages: [] });
    }
    return json({ ...position(), z: 13, work_z: 13 });
  }));
  return state;
}
type State = ReturnType<typeof network>;
const posts = (state: State, suffix: string) => state.posts.filter((entry) => entry.path.endsWith(suffix));
function view(gantry = config(), open = true, status = "Idle") {
  return <CalibrationWizard open={open} onClose={() => undefined} gantry={gantry} position={position(status)} onSaveCalibrated={async () => undefined} />;
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
async function recover(state: State, user: ReturnType<typeof userEvent.setup>, multi = false) {
  state.trip = true;
  await user.click(screen.getByTitle("Z-"));
  return screen.findByRole("button", { name: multi ? "Home and restart calibration" : "Home and resume" });
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("single-tool calibration resume", () => {
  it("uses explicit prepare-origin Home and resumes Set Origin with settings intact", async () => {
    const state = network(); const user = userEvent.setup();
    render(view()); await enter(user);
    const home = await recover(state, user);
    expect(posts(state, "/prepare-origin")).toHaveLength(1);
    await user.click(home);
    expect(await screen.findByRole("heading", { name: "Set Origin" })).toBeInTheDocument();
    expect(posts(state, "/prepare-origin")).toHaveLength(2);
    expect(screen.getByLabelText("Tip attached")).toBeChecked();
    expect(screen.getByLabelText("Measured length (mm)")).toHaveValue("70");
    expect(posts(state, "/work-coordinates")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Set origin" }));
    expect(await screen.findByText(/saved to measured.yaml/)).toBeInTheDocument();
    expect(posts(state, "/work-coordinates")[0].body).toEqual({ x: 0, y: 0, z: 13 });
  });

  it("discards an already captured origin when resuming from Save", async () => {
    const state = network(); const user = userEvent.setup();
    const { rerender } = render(view()); await enter(user);
    await user.click(screen.getByRole("button", { name: "Set origin" }));
    await screen.findByRole("button", { name: "Save" });
    rerender(view(config(), true, "Home required"));
    await user.click(await screen.findByRole("button", { name: "Home and resume" }));
    expect(await screen.findByRole("heading", { name: "Set Origin" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(posts(state, "/work-coordinates")).toHaveLength(1);
  });

  it.each(["normal", "early recovery"])("keeps the reference-height step for %s Home", async (mode) => {
    network(); const user = userEvent.setup();
    render(view(config(), true, mode === "normal" ? "Idle" : "Home required"));
    if (mode === "normal") await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: mode === "normal" ? "Home gantry" : "Home and resume" }));
    expect(await screen.findByLabelText("Reference height (mm)")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Set Origin" })).not.toBeInTheDocument();
  });

  it("keeps multi-tool XY restart and its entered tool, block and tip settings", async () => {
    const state = network(); const user = userEvent.setup();
    render(view(config(true)));
    await user.selectOptions(screen.getByLabelText("Lowest instrument"), "pipette");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));
    await user.click(screen.getByRole("button", { name: "Set XY origin and continue" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByLabelText("Measured length (mm)"), "70");
    await user.click(await recover(state, user, true));
    expect(await screen.findByRole("heading", { name: "Set XY Origin" })).toBeInTheDocument();
    expect(posts(state, "/work-coordinates")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Set XY origin and continue" }));
    expect(await screen.findByLabelText("Block height (mm)")).toHaveValue("13");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByLabelText("Measured length (mm)")).toHaveValue("70");
    expect(screen.getByRole("button", { name: "Set Z reference with pipette and continue" })).toBeEnabled();
  });

  it("does not accept an unverified recovery Home", async () => {
    const state = network(); const user = userEvent.setup();
    render(view()); await enter(user);
    const home = await recover(state, user);
    state.homeResult = { ...position(), status: "Run" };
    await user.click(home);
    expect(await screen.findByText("Homing is unverified: Run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set origin" })).toBeDisabled();
    expect(posts(state, "/work-coordinates")).toHaveLength(0);
  });

  it("sends one Home and ignores its late result after closing and reopening", async () => {
    const state = network(); const user = userEvent.setup();
    const { rerender } = render(view()); await enter(user);
    const home = await recover(state, user);
    let finish!: (response: Response) => void;
    state.pendingHome = new Promise<Response>((resolve) => { finish = resolve; });
    act(() => { home.click(); home.click(); });
    expect(posts(state, "/prepare-origin")).toHaveLength(2);
    rerender(view(config(), false)); rerender(view());
    state.pendingHome = null;
    await enter(user);
    await act(async () => finish(json({ ...position(), z: 0, work_z: 0 })));
    expect(screen.getByRole("heading", { name: "Set Origin" })).toBeInTheDocument();
    expect(screen.queryByText("Homed.")).not.toBeInTheDocument();
  });
});
