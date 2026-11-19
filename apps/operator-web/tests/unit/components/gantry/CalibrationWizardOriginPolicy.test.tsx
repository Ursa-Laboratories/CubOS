import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationWizard from "../../../../src/components/gantry/CalibrationWizard";
import type { GantryConfig, GantryPosition } from "../../../../src/types";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function singleInstrumentConfig(): GantryConfig {
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
    grbl_settings: {},
    instruments: {
      asmi: { type: "asmi", vendor: "vernier", offset_x: 0, offset_y: 0, depth: 0 },
    },
  };
}

function multiInstrumentConfig(): GantryConfig {
  return {
    ...singleInstrumentConfig(),
    instruments: {
      asmi: { type: "asmi", vendor: "vernier", offset_x: 0, offset_y: 0, depth: 0 },
      pipette: { type: "pipette", vendor: "opentrons", offset_x: 0, offset_y: 0, depth: 0 },
    },
  };
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
  const fetchMock = vi.fn(async () => jsonResponse(position()));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("CalibrationWizard origin_policy copy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses front-left wording for deck_origin (default) single-instrument configs", async () => {
    const user = userEvent.setup();
    installFetch();
    const config: GantryConfig = singleInstrumentConfig();

    render(
      <CalibrationWizard
        open
        onClose={() => undefined}
        gantry={{ filename: "cubos.yaml", config }}
        position={position()}
        onSaveCalibrated={async () => undefined}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Continue" })); // Prepare -> Home
    await user.click(await screen.findByRole("button", { name: "Home gantry" })); // -> Reference height
    await user.click(await screen.findByRole("button", { name: "Continue" })); // -> Set Origin

    expect(await screen.findByText(/front-left corner of the deck/)).toBeInTheDocument();
    expect(screen.queryByText(/back-right corner of the deck/)).not.toBeInTheDocument();
  });

  it.each(["single", "multi"])("blocks legacy %s calibration before any hardware request", async (mode) => {
    const user = userEvent.setup();
    const fetch = installFetch();
    const config = Object.assign(mode === "multi" ? multiInstrumentConfig() : singleInstrumentConfig(), {
      origin_policy: "home_origin",
    }) as unknown as GantryConfig;
    render(<CalibrationWizard open onClose={() => undefined}
      gantry={{ filename: "legacy.yaml", config }} position={position()} onSaveCalibrated={async () => undefined} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Unsupported coordinate origin");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.queryByRole("button", { name: "Home gantry" })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});
