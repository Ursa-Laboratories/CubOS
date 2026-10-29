import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationWizard from "./CalibrationWizard";
import type { GantryConfig, GantryPosition } from "../../types";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function gantryConfig(): GantryConfig {
  return {
    serial_port: "/dev/ttyUSB0",
    gantry_type: "cub_xl",
    cnc: {
      factory_z_travel_mm: 110,
      calibration_block_height_mm: 35,
      y_axis_motion: "head",
      safe_z: 110,
    },
    working_volume: {
      x_min: 0,
      x_max: 400,
      y_min: 0,
      y_max: 300,
      z_min: 0,
      z_max: 110,
    },
    grbl_settings: {},
    instruments: {
      asmi: {
        type: "asmi",
        vendor: "vernier",
        offset_x: 0,
        offset_y: 0,
        depth: 0,
      },
    },
  };
}

function position(status = "Idle"): GantryPosition {
  return {
    x: 0,
    y: 0,
    z: 20,
    work_x: 0,
    work_y: 0,
    work_z: 20,
    status,
    connected: true,
    calibration_active: false,
  };
}

async function advanceToOriginJog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(await screen.findByRole("button", { name: "Home gantry" }));
  await user.click(await screen.findByRole("button", { name: "Continue" }));
  return screen.findByRole("button", { name: "Z-" });
}

describe("CalibrationWizard alarm recovery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("clears a prior Home required poll only after verified homing succeeds", async () => {
    const user = userEvent.setup();
    let finishHome!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finishHome = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/prepare-origin") ? pending : jsonResponse(position())));
    const wizard = (status: string) => <CalibrationWizard open onClose={() => undefined}
      gantry={{ filename: "cubos.yaml", config: gantryConfig() }} position={position(status)}
      onSaveCalibrated={async () => undefined} />;
    const { rerender } = render(wizard("Idle"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));
    rerender(wizard("Home required"));
    finishHome(jsonResponse(position()));
    await screen.findByText("Homed.");
    rerender(wizard("Idle"));
    expect(screen.queryByText("GANTRY ALARM")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    rerender(wizard("ALARM:3; Pn:Y"));
    expect(await screen.findByText("GANTRY ALARM")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it.each(["Home required", "Homing", "ALARM:3"])("does not report Homed for an unverified %s response", async (status) => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(position(status))));
    render(<CalibrationWizard open onClose={() => undefined}
      gantry={{ filename: "cubos.yaml", config: gantryConfig() }} position={position()}
      onSaveCalibrated={async () => undefined} />);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));
    expect(screen.queryByText("Homed.")).not.toBeInTheDocument();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Home");
  });

  it("shows the power-cycle instruction when recovery reports connection loss", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
      if (url.pathname === "/api/v1/gantry/jog" && init?.method === "POST") {
        return new Response(JSON.stringify({ detail: "ALARM:1" }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.pathname === "/api/v1/gantry/unlock" && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            detail:
              "Controller connection lost during limit recovery. Power-cycle the controller, re-seat the USB cable, then Disconnect and Connect again before continuing.",
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        );
      }
      return jsonResponse(position());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CalibrationWizard
        open
        onClose={() => undefined}
        gantry={{ filename: "cubos.yaml", config: gantryConfig() }}
        position={position()}
        onSaveCalibrated={async () => undefined}
      />,
    );

    const zDown = await advanceToOriginJog(user);
    await user.click(zDown);

    await user.click(await screen.findByRole("button", { name: "Unlock alarm" }));
    expect(await screen.findByText(/Power-cycle the controller, re-seat the USB cable/)).toBeInTheDocument();
  });

  it("closes even when restoring soft limits fails (dead controller link)", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
      if (url.pathname === "/api/v1/gantry/calibration/restore-soft-limits") {
        return new Response(JSON.stringify({ detail: "serial read timed out" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        });
      }
      return jsonResponse(position());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CalibrationWizard
        open
        onClose={onClose}
        gantry={{ filename: "cubos.yaml", config: gantryConfig() }}
        position={position()}
        onSaveCalibrated={async () => undefined}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Close calibration" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("resets the wizard and surfaces the error when restore fails", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(typeof input === "string" ? input : (input as Request).url, "http://localhost");
      if (url.pathname === "/api/v1/gantry/calibration/restore-soft-limits") {
        return new Response(JSON.stringify({ detail: "serial read timed out" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        });
      }
      return jsonResponse(position());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CalibrationWizard
        open
        onClose={() => undefined}
        gantry={{ filename: "cubos.yaml", config: gantryConfig() }}
        position={position()}
        onSaveCalibrated={async () => undefined}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Reset wizard" }));

    expect(await screen.findByText(/Failed to restore soft limits/)).toBeInTheDocument();
    // The wizard still reset to the first step instead of staying trapped.
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Prepare");
  });

  it("tells the operator to jog in small steps near the edges of travel", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(position())));

    render(
      <CalibrationWizard
        open
        onClose={() => undefined}
        gantry={{ filename: "cubos.yaml", config: gantryConfig() }}
        position={position()}
        onSaveCalibrated={async () => undefined}
      />,
    );

    expect(screen.getByText(/Jog in small steps near the edges of travel/)).toBeInTheDocument();
  });

  it.each(["ALARM:1 hard limit", "ALARM:3", "error:9 Reset to continue", "[MSG:Check Limits]"])("locks controls without automatic recovery after %s", async (message) => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/jog")
      ? new Response(message, { status: 409 }) : jsonResponse(position()));
    vi.stubGlobal("fetch", fetchMock);
    render(<CalibrationWizard open onClose={() => undefined}
      gantry={{ filename: "cubos.yaml", config: gantryConfig() }} position={position()}
      onSaveCalibrated={async () => undefined} />);
    await user.click(await advanceToOriginJog(user));
    expect(await screen.findByText("GANTRY ALARM")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Z-" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set origin and continue" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/recover-limit"))).toBe(false);
  });

  it("retains a polled fault across cached Idle without automatic pull-off", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => jsonResponse(position()));
    vi.stubGlobal("fetch", fetchMock);
    const wizard = (status: string) => <CalibrationWizard open onClose={() => undefined}
      gantry={{ filename: "cubos.yaml", config: gantryConfig() }} position={position(status)}
      onSaveCalibrated={async () => undefined} />;
    const { rerender } = render(wizard("Idle"));
    await user.click(await advanceToOriginJog(user));
    rerender(wizard("<Idle|WPos:0,0,20|Pn:Z>"));
    expect(await screen.findByText("GANTRY ALARM")).toBeInTheDocument();
    rerender(wizard("Idle"));
    expect(screen.getByRole("button", { name: "Z-" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/recover-limit"))).toBe(false);
  });

  it("does not advance after a calibration lift faults", async () => {
    const user = userEvent.setup();
    const config = gantryConfig();
    config.instruments.camera = { type: "camera", vendor: "usb", offset_x: 0, offset_y: 0, depth: 0 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/home-and-center")) return jsonResponse({ xy_bounds: { x: 100, y: 100, z: 20 }, position: { x: 50, y: 50, z: 20 } });
      if (path.endsWith("/position")) return jsonResponse({ ...position(), z: -50, work_z: -50 });
      if (path.endsWith("/jog-blocking")) return new Response("ALARM:1 hard limit", { status: 409 });
      return jsonResponse(position());
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CalibrationWizard open onClose={() => undefined}
      gantry={{ filename: "cubos.yaml", config }} position={position()}
      onSaveCalibrated={async () => undefined} />);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Home gantry" }));
    await user.click(await screen.findByRole("button", { name: "Set XY origin and continue" }));
    await user.click(await screen.findByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Set Z reference with asmi and continue" }));
    expect(await screen.findByText("GANTRY ALARM")).toBeInTheDocument();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Z reference");
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/recover-limit"))).toBe(false);
  });
});
