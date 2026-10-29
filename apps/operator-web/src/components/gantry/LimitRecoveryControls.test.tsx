import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import LimitRecoveryControls from "./LimitRecoveryControls";
import type { LimitRecoveryContext, LimitRecoveryResult } from "../../api/client";

function context(overrides: Partial<LimitRecoveryContext> = {}): LimitRecoveryContext {
  return { raw_status: "ALARM:3; Pn:Y", active_limit_axes: ["y"], failed_jog_delta: { x: 0, y: 0.5, z: 0 }, eligible: true, blocked_reason: null, pull_off_delta: { x: 0, y: -5, z: 0 }, manual_available: true, ...overrides };
}
function result(mode: "known_jog" | "manual" = "known_jog"): LimitRecoveryResult {
  const delta = { x: 0, y: mode === "manual" ? -1 : -5, z: 0 };
  return { status: "recovered", attempts: 1, pull_off: delta, messages: [], mode, commanded_delta: delta, failed_delta: mode === "manual" ? null : { x: 0, y: 0.5, z: 0 } };
}
function json(value: unknown) { return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }); }
function props() { return { connected: true, disabled: false, onStart: vi.fn(), onBusyChange: vi.fn(), onRecovered: vi.fn(), onError: vi.fn() }; }
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("shared limit recovery controls", () => {
  it("uses the server's Y candidate without any local jog and never starts automatically", async () => {
    const user = userEvent.setup();
    const callbacks = props();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => json(String(input).endsWith("/recovery-context") ? context() : result()));
    vi.stubGlobal("fetch", fetchMock);
    render(<LimitRecoveryControls {...callbacks} />);
    const action = await screen.findByRole("button", { name: "Pull off Y− 5 mm" });
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/recover-limit"))).toBe(false);
    await user.click(action);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/gantry/calibration/recover-limit", expect.objectContaining({ method: "POST", body: JSON.stringify({ x: 0, y: 0.5, z: 0 }) }));
    expect(callbacks.onRecovered).toHaveBeenCalledWith(result());
  });

  it("requires an explicit away direction and path-clear confirmation for manual 1 mm", async () => {
    const user = userEvent.setup();
    const callbacks = props();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => json(String(input).endsWith("/recovery-context")
      ? context({ failed_jog_delta: null, eligible: false, blocked_reason: "Original jog unknown.", pull_off_delta: null }) : result("manual")));
    vi.stubGlobal("fetch", fetchMock);
    render(<LimitRecoveryControls {...callbacks} />);
    await user.click(await screen.findByText("Manual recovery"));
    const direction = screen.getByLabelText("Away direction");
    expect(direction).toHaveValue("");
    expect(screen.getByRole("button", { name: "Move Y 1 mm" })).toBeDisabled();
    await user.selectOptions(direction, "-1");
    expect(screen.getByRole("button", { name: "Move Y− 1 mm" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Move Y− 1 mm" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/gantry/calibration/recover-limit/manual", expect.objectContaining({ method: "POST", body: JSON.stringify({ axis: "y", away_direction: -1, operator_confirmed: true }) }));
    expect(callbacks.onRecovered).toHaveBeenCalledWith(result("manual"));
  });

  it("keeps Stop available while recovery is pending and does not claim success after cancelling", async () => {
    const user = userEvent.setup();
    const callbacks = props();
    let finish!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finish = resolve; });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/recover-limit") ? pending : json(context()));
    vi.stubGlobal("fetch", fetchMock);
    render(<LimitRecoveryControls {...callbacks} />);
    await user.click(await screen.findByRole("button", { name: "Pull off Y− 5 mm" }));
    await user.click(screen.getByRole("button", { name: "Stop recovery" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/gantry/jog-cancel", expect.objectContaining({ method: "POST" }));
    await act(async () => finish(json(result())));
    expect(callbacks.onRecovered).not.toHaveBeenCalled();
    expect(callbacks.onError).toHaveBeenCalledWith(expect.stringMatching(/Recovery stopped/));
  });

  it("hides recovery actions when the server cannot verify a single active switch", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(context({ active_limit_axes: ["x", "y"], eligible: false, manual_available: false, blocked_reason: "Multiple active switches.", failed_jog_delta: null, pull_off_delta: null }))));
    render(<LimitRecoveryControls {...props()} />);
    expect(await screen.findByText("Multiple active switches.")).toBeInTheDocument();
    expect(screen.queryByText("Manual recovery")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pull off/ })).not.toBeInTheDocument();
  });

  it("shares at most one context read per second across multiple alarm views", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => json(context()));
    vi.stubGlobal("fetch", fetchMock);
    render(<><LimitRecoveryControls {...props()} /><LimitRecoveryControls {...props()} /></>);
    await act(async () => undefined);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(999); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("requires a new direction and confirmation when the active axis changes", async () => {
    vi.useFakeTimers();
    let axis: "x" | "y" = "y";
    vi.stubGlobal("fetch", vi.fn(async () => json(context({ active_limit_axes: [axis], failed_jog_delta: null, eligible: false, pull_off_delta: null }))));
    render(<LimitRecoveryControls {...props()} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByText("Manual recovery"));
    fireEvent.change(screen.getByLabelText("Away direction"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Move Y+ 1 mm" })).toBeEnabled();
    axis = "x";
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(screen.getByLabelText("Away direction")).toHaveValue("");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Move X 1 mm" })).toBeDisabled();
  });

  it("sends only one recovery command for a double click and cancels on close", async () => {
    const callbacks = props();
    let finish!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finish = resolve; });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/recover-limit") ? pending : json(context()));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<LimitRecoveryControls {...callbacks} />);
    const action = await screen.findByRole("button", { name: "Pull off Y− 5 mm" });
    act(() => { action.click(); action.click(); });
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/recover-limit"))).toHaveLength(1);
    view.unmount();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/gantry/jog-cancel", expect.objectContaining({ method: "POST" }));
    await act(async () => finish(json(result())));
    expect(callbacks.onRecovered).not.toHaveBeenCalled();
  });
});
