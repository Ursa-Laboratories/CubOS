import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationWizard from "./CalibrationWizard";
import type { GantryConfig, GantryPosition } from "../../types";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function multiConfig(): GantryConfig {
  return {
    serial_port: "/dev/ttyUSB0",
    gantry_type: "cub_xl",
    cnc: {
      factory_z_travel_mm: 110,
      calibration_block_height_mm: 35,
      y_axis_motion: "head",
      safe_z: 110,
    },
    working_volume: { x_min: 0, x_max: 400, y_min: 0, y_max: 300, z_min: 0, z_max: 110 },
    // No homing_pull_off seeded — calibration should still proceed (defaulted).
    grbl_settings: {},
    instruments: {
      asmi: { type: "asmi", vendor: "vernier", offset_x: 0, offset_y: 0, depth: 0 },
      pipette: { type: "pipette", vendor: "opentrons", offset_x: 0, offset_y: 0, depth: 0 },
    },
  };
}

function multiConfigWithCamera(): GantryConfig {
  const config = multiConfig();
  config.instruments = {
    asmi: { type: "asmi", vendor: "vernier", offset_x: 0, offset_y: 0, depth: 0 },
    camera: {
      type: "camera",
      vendor: "raspberry_pi",
      offset_x: 0,
      offset_y: 0,
      depth: 0,
      offline: true,
    },
  };
  return config;
}

function lowTravelMultiConfig(): GantryConfig {
  const config = multiConfig();
  config.cnc.factory_z_travel_mm = 80;
  config.cnc.safe_z = 80;
  config.working_volume.z_max = 80;
  return config;
}

function position(): GantryPosition {
  return {
    x: 0,
    y: 0,
    z: 20,
    work_x: 0,
    work_y: 0,
    work_z: 20,
    status: "Idle",
    connected: true,
    calibration_active: false,
  };
}

function installFetch() {
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
      "http://localhost",
    );
    if (url.pathname === "/api/gantry/calibration/home-and-center" && init?.method === "POST") {
      return jsonResponse({ xy_bounds: { x: 400, y: 300, z: 110 }, position: { x: 200, y: 150, z: 110 } });
    }
    return jsonResponse(position());
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function advanceToBlockHeightStep(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Continue" })); // Prepare -> Home
  await user.click(await screen.findByRole("button", { name: "Home gantry" })); // -> XY origin
  await user.click(await screen.findByRole("button", { name: "Set XY origin and continue" })); // -> Block height
}

describe("CalibrationWizard multi-instrument block height step", () => {
  afterEach(() => vi.unstubAllGlobals());

  function renderWizard() {
    render(
      <CalibrationWizard
        open
        onClose={() => undefined}
        gantry={{ filename: "multi.yaml", config: multiConfig() }}
        position={position()}
        onSaveCalibrated={async () => undefined}
      />,
    );
  }

  it("starts calibration even when the YAML omits homing_pull_off", async () => {
    const user = userEvent.setup();
    installFetch();
    renderWizard();

    await user.click(screen.getByRole("button", { name: "Continue" })); // Prepare -> Home
    // No "requires grbl_settings.homing_pull_off" block — we reach the Home step.
    expect(await screen.findByRole("button", { name: "Home gantry" })).toBeInTheDocument();
    expect(screen.queryByText(/homing_pull_off/i)).not.toBeInTheDocument();
  });

  it("lists Block height as its own step between XY origin and Z reference", () => {
    installFetch();
    renderWizard();
    const steps = screen.getByLabelText("Gantry calibration").querySelectorAll("aside > div");
    expect(Array.from(steps).map((s) => s.textContent)).toEqual([
      "1Prepare",
      "2Home",
      "3XY origin",
      "4Block height",
      "5Z reference",
      "6Instruments",
      "7Save",
    ]);
  });

  it("lets the operator edit the block height and carries it into Z reference", async () => {
    const user = userEvent.setup();
    installFetch();
    renderWizard();

    await advanceToBlockHeightStep(user);

    // The block height field is editable (not locked at the config's 35).
    const blockHeight = await screen.findByLabelText("Block height (mm)");
    expect(blockHeight).toBeEnabled();
    expect(blockHeight).toHaveValue("35");
    await user.clear(blockHeight);
    await user.type(blockHeight, "42");

    await user.click(screen.getByRole("button", { name: "Continue" })); // -> Z reference

    expect(await screen.findByText("Set Z Reference")).toBeInTheDocument();
    expect(screen.getByText("42 mm")).toBeInTheDocument();
  });

  it("blocks advancing from the block height step when the value is invalid", async () => {
    const user = userEvent.setup();
    installFetch();
    renderWizard();

    await advanceToBlockHeightStep(user);
    const blockHeight = await screen.findByLabelText("Block height (mm)");
    await user.clear(blockHeight);
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText(/Enter a calibration reference height/i)).toBeInTheDocument();
    expect(screen.queryByText("Set Z Reference")).not.toBeInTheDocument();
  });

  it("requires the rpi camera block distance before recording the camera position", async () => {
    const user = userEvent.setup();
    installFetch();
    render(
      <CalibrationWizard
        open
        onClose={() => undefined}
        gantry={{ filename: "multi-rpi.yaml", config: multiConfigWithCamera() }}
        position={position()}
        onSaveCalibrated={async () => undefined}
      />,
    );

    await advanceToBlockHeightStep(user);
    await user.click(screen.getByRole("button", { name: "Continue" })); // -> Z reference
    await user.click(await screen.findByRole("button", { name: "Set Z reference with asmi and retract" }));

    expect(await screen.findByText("Record Instruments")).toBeInTheDocument();
    expect(screen.getByText(/Center the camera over the calibration block mark/i)).toBeInTheDocument();

    const recordButton = screen.getByRole("button", { name: "Record camera" });
    expect(recordButton).toBeDisabled();
    const distance = screen.getByLabelText("Distance from calibration block (mm)");
    await user.type(distance, "20");

    expect(recordButton).toBeEnabled();
  });

  it("retries a failed Z retract without re-zeroing in the shifted frame", async () => {
    const user = userEvent.setup();
    const onSaveCalibrated = vi.fn<(filename: string, config: GantryConfig) => Promise<void>>(async () => undefined);
    let positionReadCount = 0;
    let setWorkCoordinateCount = 0;
    let retractFailuresRemaining = 1;
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
        "http://localhost",
      );
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      if (url.pathname === "/api/gantry/calibration/prepare-origin" && init?.method === "POST") {
        return jsonResponse({ ...position(), z: 90, work_z: 90 });
      }
      if (url.pathname === "/api/gantry/calibration/home-and-center" && init?.method === "POST") {
        return jsonResponse({
          xy_bounds: { x: 400, y: 300, z: 90 },
          position: { x: 200, y: 150, z: 90 },
        });
      }
      if (url.pathname === "/api/gantry/position") {
        positionReadCount++;
        const z = positionReadCount === 1 ? 55 : 35;
        return jsonResponse({ ...position(), z, work_z: z });
      }
      if (url.pathname === "/api/gantry/work-coordinates" && init?.method === "POST") {
        setWorkCoordinateCount++;
        return jsonResponse({ ...position(), z: body?.z ?? 35, work_z: body?.z ?? 35 });
      }
      if (url.pathname === "/api/gantry/jog-blocking" && init?.method === "POST") {
        if (retractFailuresRemaining > 0) {
          retractFailuresRemaining--;
          return new Response("retract failed", { status: 500 });
        }
        return jsonResponse({ ...position(), z: 50, work_z: 50 });
      }
      if (url.pathname === "/api/gantry/home" && init?.method === "POST") {
        return jsonResponse({ ...position(), x: 400, y: 300, z: 88, work_x: 400, work_y: 300, work_z: 88 });
      }
      if (url.pathname === "/api/gantry/soft-limits" && init?.method === "POST") {
        return jsonResponse({ status: "ok" });
      }
      return jsonResponse(position());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CalibrationWizard
        open
        onClose={() => undefined}
        gantry={{ filename: "multi.yaml", config: lowTravelMultiConfig() }}
        position={position()}
        onSaveCalibrated={onSaveCalibrated}
      />,
    );

    await advanceToBlockHeightStep(user);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    const setZ = await screen.findByRole("button", { name: "Set Z reference with asmi and retract" });

    await user.click(setZ);
    expect(await screen.findByText("retract failed")).toBeInTheDocument();

    await user.click(setZ);
    expect(await screen.findByText("Record Instruments")).toBeInTheDocument();
    expect(setWorkCoordinateCount).toBe(2);
    const workCoordinateBodies = fetchMock.mock.calls.filter(([input]) => {
      const url = new URL(
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
        "http://localhost",
      );
      return url.pathname === "/api/gantry/work-coordinates";
    }).map(([, init]) => JSON.parse(String(init?.body)));
    expect(workCoordinateBodies).toHaveLength(2);
    expect(workCoordinateBodies.filter((body) => "z" in body)).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Record pipette and retract" }));
    expect(await screen.findByText("Measure And Save")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSaveCalibrated).toHaveBeenCalled());
    const savedConfig = onSaveCalibrated.mock.calls[0][1] as GantryConfig;
    expect(savedConfig.working_volume.z_min).toBe(0);
    expect(savedConfig.working_volume.z_max).toBe(88);
  });

  it("keeps focus inside the modal and closes with Escape when idle", async () => {
    const onClose = vi.fn();
    installFetch();
    render(
      <>
        <button type="button">Background Home</button>
        <CalibrationWizard
          open
          onClose={onClose}
          gantry={{ filename: "multi.yaml", config: multiConfig() }}
          position={position()}
          onSaveCalibrated={async () => undefined}
        />
      </>,
    );

    const dialog = screen.getByRole("dialog", { name: "Gantry calibration" });
    await waitFor(() => expect(dialog).toHaveFocus());

    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Reset wizard" })).toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(screen.getByRole("button", { name: "Background Home" })).not.toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
