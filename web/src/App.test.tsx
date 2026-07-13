import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type {
  DeckConfig,
  DeckResponse,
  GantryConfig,
  GantryPosition,
  GantryResponse,
  ProtocolConfig,
  ProtocolResponse,
  ProtocolRunStatus,
  WellPlateConfig,
  WellPosition,
} from "./types";

type ApiState = {
  decks: Record<string, DeckResponse>;
  gantries: Record<string, GantryResponse>;
  protocols: Record<string, ProtocolResponse>;
};

type FetchMockOptions = {
  protocolRun?: (init?: RequestInit) => Promise<Response>;
  protocolCancel?: () => Response | Promise<Response>;
  runStatus?: () => ProtocolRunStatus;
  validateSetup?: () => Response | Promise<Response>;
  calibrationWarning?: string | null;
};

function createState(): ApiState {
  return {
    decks: {
      "deck.yaml": {
        filename: "deck.yaml",
        labware: [
          {
            key: "plate_1",
            config: {
              type: "well_plate",
              name: "Deck Plate",
              model_name: "plate-model",
              rows: 8,
              columns: 12,
              length: 127.76,
              width: 85.47,
              height: 14.22,
              a1: null,
              calibration: {
                a1: { x: 10, y: 20, z: 30 },
                a2: { x: 20, y: 20, z: 30 },
              },
              x_offset: 9,
              y_offset: 9,
              capacity_ul: 200,
              working_volume_ul: 150,
            },
            wells: null,
          },
        ],
      },
    },
    gantries: {
      "cubos.yaml": {
        filename: "cubos.yaml",
        config: {
          serial_port: "",
          gantry_type: "cub_xl",
          cnc: {
      factory_z_travel_mm: 80,
            calibration_block_height_mm: 35,
            y_axis_motion: "head",
            safe_z: 80,
          },
          working_volume: { x_min: 0, x_max: 300, y_min: 0, y_max: 200, z_min: 0, z_max: 80 },
          grbl_settings: {},
          instruments: {
            pipette_1: {
              type: "pipette",
              vendor: "opentrons",
              offset_x: 1,
              offset_y: 2,
              depth: 0,
              port: "/dev/ttyUSB0",
            },
          },
        },
      },
    },
    protocols: {
      "move.yaml": {
        filename: "move.yaml",
        positions: {
          park: [10, 20, 30],
        },
        steps: [
          {
            command: "move",
            args: { instrument: "pipette_1", position: "plate_1.A1", travel_z: 3 },
          },
        ],
      },
    },
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function toDeckResponse(filename: string, body: DeckConfig): DeckResponse {
  return {
    filename,
    labware: Object.entries(body.labware).map(([key, config]) => ({
      key,
      config,
      wells: config.type === "well_plate" ? previewWells(config) : null,
    })),
  };
}

function previewWells(config: WellPlateConfig): Record<string, WellPosition> {
  const a1 = config.calibration.a1 ?? config.a1 ?? { x: 0, y: 0, z: 0 };
  const wells: Record<string, WellPosition> = {};
  for (let row = 0; row < config.rows; row += 1) {
    const rowName = String.fromCharCode("A".charCodeAt(0) + row);
    for (let column = 0; column < config.columns; column += 1) {
      wells[`${rowName}${column + 1}`] = {
        x: a1.x + column * config.x_offset,
        y: a1.y - row * config.y_offset,
        z: a1.z,
      };
    }
  }
  return wells;
}

function toGantryResponse(filename: string, body: GantryConfig): GantryResponse {
  return {
    filename,
    config: body,
  };
}

function toProtocolResponse(filename: string, body: ProtocolConfig): ProtocolResponse {
  return {
    filename,
    positions: body.positions,
    steps: body.protocol,
  };
}

function installFetchMock(state: ApiState, options: FetchMockOptions = {}) {
  let gantryConnected = false;
  const gantryPosition = (x = 0, y = 0, z = 0): GantryPosition => ({
    x,
    y,
    z,
    work_x: x,
    work_y: y,
    work_z: z,
    status: "Idle",
    connected: gantryConnected,
    calibration_active: false,
    calibration_warning: options.calibrationWarning ?? null,
  });

  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
      "http://localhost",
    );
    const path = url.pathname;
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;

    if (path === "/api/settings" && method === "GET") {
      return jsonResponse({ config_dir: "/mock/Zoo/configs" });
    }
    if (path === "/api/settings/browse" && method === "POST") {
      return jsonResponse({ config_dir: "/mock/Zoo/selected-configs" });
    }
    if (path === "/api/settings" && method === "PUT") {
      return jsonResponse({ config_dir: body?.config_dir ?? "/mock/Zoo/configs" });
    }
    if (path === "/api/deck/configs") {
      return jsonResponse(Object.keys(state.decks));
    }
    if (path === "/api/gantry/configs") {
      return jsonResponse(Object.keys(state.gantries));
    }
    if (path === "/api/protocol/configs") {
      return jsonResponse(Object.keys(state.protocols));
    }
    if (path === "/api/gantry/instrument-types") {
      return jsonResponse([{ type: "pipette", vendors: ["opentrons"], is_mock: false }]);
    }
    if (path === "/api/gantry/instrument-schemas") {
      return jsonResponse({
        pipette: {
          opentrons: [
            { name: "port", type: "str", required: true, default: "/dev/ttyUSB0", choices: null },
          ],
        },
      });
    }
    if (path === "/api/gantry/instrument-methods") {
      return jsonResponse({
        asmi: ["indentation", "measure"],
        filmetrics: ["measure"],
        pipette: [],
        uv_curing: ["measure"],
        uvvis_ccs: ["measure"],
      });
    }
    if (path === "/api/protocol/commands") {
      return jsonResponse([
        {
          name: "move",
          args: [
            { name: "instrument", type: "str", required: true, default: null },
            { name: "position", type: "Any", required: true, default: null },
            { name: "travel_z", type: "float | None", required: false, default: null },
          ],
          description: "Move gantry",
        },
        {
          name: "scan",
          args: [
            { name: "plate", type: "str", required: true, default: null },
            { name: "instrument", type: "str", required: true, default: null },
            { name: "method", type: "str", required: true, default: null },
            { name: "measurement_height", type: "float", required: true, default: null },
            { name: "interwell_scan_height", type: "float", required: true, default: null },
            { name: "indentation_limit_height", type: "float | None", required: false, default: null },
            { name: "method_kwargs", type: "Dict[str, Any] | None", required: false, default: null },
          ],
          description: "Scan plate",
        },
      ]);
    }
    if (path === "/api/protocol/run" && method === "POST") {
      if (options.protocolRun) return options.protocolRun(init);
      return jsonResponse({ status: "complete", steps_executed: 1, campaign_id: 123 });
    }
    if (path === "/api/protocol/cancel" && method === "POST") {
      if (options.protocolCancel) return options.protocolCancel();
      return jsonResponse({ status: "cancel_requested" });
    }
    if (path === "/api/protocol/run-status") {
      return jsonResponse(options.runStatus ? options.runStatus() : { active: false, protocol_file: null });
    }
    if (path === "/api/protocol/validate-setup" && method === "POST") {
      if (options.validateSetup) return options.validateSetup();
      return jsonResponse({
        valid: true,
        errors: [],
        output: "RESULT: PASS",
      });
    }
    if (path === "/api/gantry/position") {
      return jsonResponse(gantryPosition());
    }
    if (path === "/api/gantry/connect" && method === "POST") {
      gantryConnected = true;
      return jsonResponse(gantryPosition());
    }
    if (path === "/api/gantry/disconnect" && method === "POST") {
      gantryConnected = false;
      return jsonResponse(gantryPosition());
    }
    if (path === "/api/gantry/calibration/prepare-origin" && method === "POST") {
      gantryConnected = true;
      return jsonResponse(gantryPosition(0, 0, 80));
    }
    if (path === "/api/gantry/calibration/home-and-center" && method === "POST") {
      gantryConnected = true;
      return jsonResponse({
        xy_bounds: { x: 300, y: 200, z: 80 },
        position: { x: 150, y: 100, z: 80 },
      });
    }
    if (path === "/api/gantry/calibration/restore-soft-limits" && method === "POST") {
      return jsonResponse(gantryPosition());
    }
    if (path === "/api/gantry/work-coordinates" && method === "POST") {
      return jsonResponse(gantryPosition(body?.x ?? 0, body?.y ?? 0, body?.z ?? 0));
    }
    if (path === "/api/gantry/calibration/finalize-origin" && method === "POST") {
      return jsonResponse({
        measured_volume: { x: 300, y: 200, z: 80 },
        z_calibration: {
          block_height: body?.block_height ?? 35,
          total_z_range: body?.factory_z_travel ?? 80,
          home_z: body?.home_z ?? 80,
          block_touch_z: body?.block_touch_z ?? 0,
          home_to_block_travel: 45,
          remaining_below_block: 35,
          can_reach_deck_bottom: true,
          z_min: 0,
          z_max: 80,
          max_travel_z: 80,
        },
        max_travel: { x: 310, y: 210, z: 90 },
        homing_pull_off_mm: 10,
        position: { x: 300, y: 200, z: 80 },
      });
    }
    if (path === "/api/gantry/jog-blocking" && method === "POST") {
      return jsonResponse(gantryPosition(0, 0, body?.z ?? 0));
    }
    if (path === "/api/gantry/home" && method === "POST") {
      return jsonResponse(gantryPosition(300, 200, 80));
    }
    if (path === "/api/gantry/soft-limits" && method === "POST") {
      return jsonResponse({ status: "ok" });
    }
    if (path === "/api/deck/preview-wells" && method === "POST") {
      return jsonResponse(previewWells(body as WellPlateConfig));
    }

    const [, api, kind, filename] = path.split("/");
    if (api !== "api" || !filename) {
      return new Response("Not found", { status: 404 });
    }

    if (kind === "deck") {
      if (method === "GET") return jsonResponse(state.decks[filename]);
      if (method === "PUT") {
        state.decks[filename] = toDeckResponse(filename, body as DeckConfig);
        return jsonResponse(state.decks[filename]);
      }
    }
    if (kind === "gantry") {
      if (method === "GET") return jsonResponse(state.gantries[filename]);
      if (method === "PUT") {
        state.gantries[filename] = toGantryResponse(filename, body as GantryConfig);
        return jsonResponse(state.gantries[filename]);
      }
    }
    if (kind === "protocol") {
      if (method === "GET") return jsonResponse(state.protocols[filename]);
      if (method === "PUT") {
        state.protocols[filename] = toProtocolResponse(filename, body as ProtocolConfig);
        return jsonResponse({ status: "ok", filename });
      }
    }

    return new Response("Not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
      },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

async function importConfig(user: ReturnType<typeof userEvent.setup>, label: string, filename: string) {
  await user.selectOptions(screen.getByRole("combobox", { name: label }), filename);
}

async function waitForSettingsLoad() {
  await screen.findByDisplayValue("/mock/Zoo/configs");
}

async function loadRequiredProtocolDependencies(user: ReturnType<typeof userEvent.setup>) {
  await importConfig(user, "Import gantry config", "cubos.yaml");
  await user.click(screen.getByRole("button", { name: "Deck" }));
  await importConfig(user, "Import deck config", "deck.yaml");
}

async function connectGantry(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Connect" }));
  await screen.findByRole("button", { name: "Disconnect" });
}

describe("Zoo editor interactions", () => {
  beforeEach(() => {
    installFetchMock(createState());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a browse button for the config directory", async () => {
    renderApp();
    await waitForSettingsLoad();

    expect(screen.getByDisplayValue("/mock/Zoo/configs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browse" })).toBeInTheDocument();
  });

  it("updates the config directory from browse selection", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Browse" }));

    await waitFor(() => expect(screen.getByDisplayValue("/mock/Zoo/selected-configs")).toBeInTheDocument());
  });

  it("clears loaded config selections when the config directory changes", async () => {
    const user = userEvent.setup();
    installFetchMock(createState());
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    expect(await screen.findByLabelText("Travel Z")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Browse" }));

    await waitFor(() => expect(screen.getByDisplayValue("/mock/Zoo/selected-configs")).toBeInTheDocument());
    expect(await screen.findByText("Please load Gantry, Deck configs first.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Travel Z")).not.toBeInTheDocument();
  });

  it("guards dirty config-directory changes", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock(createState());
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Deck" }));
    await importConfig(user, "Import deck config", "deck.yaml");
    const nameField = await screen.findByDisplayValue("Deck Plate");
    await user.clear(nameField);
    await user.type(nameField, "Edited Plate");

    await user.click(screen.getByRole("button", { name: "Browse" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith(
      "Discard unsaved config changes and switch config directory?",
    ));
    expect(screen.getByDisplayValue("/mock/Zoo/configs")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Edited Plate")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/settings",
      expect.objectContaining({ method: "PUT" }),
    );

    confirmSpy.mockRestore();
  });

  it("loads and saves a gantry config across tab switches", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    const serialPort = await screen.findByLabelText("Serial port");
    expect(serialPort).toHaveValue("");

    await user.type(serialPort, "/dev/ttyUSB9");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(screen.getByRole("button", { name: "Deck" }));
    await user.click(screen.getByRole("button", { name: "Gantry" }));

    await waitFor(() => expect(screen.getByLabelText("Serial port")).toHaveValue("/dev/ttyUSB9"));
  });

  it("loads and saves a deck config across tab switches", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Deck" }));
    await importConfig(user, "Import deck config", "deck.yaml");
    const nameField = await screen.findByDisplayValue("Deck Plate");
    expect(nameField).toHaveValue("Deck Plate");

    await user.clear(nameField);
    await user.type(nameField, "Renamed Plate");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(screen.getByRole("button", { name: "Gantry" }));
    await user.click(screen.getByRole("button", { name: "Deck" }));

    await waitFor(() => expect(screen.getByDisplayValue("Renamed Plate")).toBeInTheDocument());
  });

  it("imports a deck config into panda-deck.yaml", async () => {
    const user = userEvent.setup();
    const state = createState();
    installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Deck" }));
    await importConfig(user, "Import deck config", "deck.yaml");

    expect(await screen.findByDisplayValue("Deck Plate")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByPlaceholderText("panda-deck.yaml")).toBeInTheDocument());
    expect(
      state.decks["panda-deck.yaml"]?.labware.map(({ key, config }) => ({ key, config })),
    ).toEqual(
      state.decks["deck.yaml"]?.labware.map(({ key, config }) => ({ key, config })),
    );
  });

  it("uses live preview wells for loaded deck edits before saving", async () => {
    const user = userEvent.setup();
    installFetchMock(createState());
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Deck" }));
    await importConfig(user, "Import deck config", "deck.yaml");
    expect(await screen.findByText("A1: (10, 20, 30)")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Calibration A1 X"));
    await user.type(screen.getByLabelText("Calibration A1 X"), "111");

    expect(await screen.findByText("A1: (111, 20, 30)")).toBeInTheDocument();
  });

  it("loads and saves gantry instruments across tab switches", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    const portField = await screen.findByLabelText("Port *");
    expect(portField).toHaveValue("/dev/ttyUSB0");

    await user.clear(portField);
    await user.type(portField, "/dev/ttyUSB4");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(screen.getByRole("button", { name: "Deck" }));
    await user.click(screen.getByRole("button", { name: "Gantry" }));

    await waitFor(() => expect(screen.getByLabelText("Port *")).toHaveValue("/dev/ttyUSB4"));
  });

  it("saves a new gantry filename before selecting it for fetches", async () => {
    const user = userEvent.setup();
    const state = createState();
    const fetchMock = installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    expect(await screen.findByLabelText("Serial port")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("cubos.yaml"), "qa_new_gantry");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(state.gantries["qa_new_gantry.yaml"]).toBeDefined());
    const newFileCalls = fetchMock.mock.calls.filter(([input]) => {
      const url = new URL(
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
        "http://localhost",
      );
      return url.pathname === "/api/gantry/qa_new_gantry.yaml";
    });
    expect(newFileCalls.length).toBeGreaterThan(0);
    expect(newFileCalls[0][1]?.method).toBe("PUT");
  });

  it("opens the gantry calibration wizard from the control panel", async () => {
    const user = userEvent.setup();
    const state = createState();
    const fetchMock = installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    await user.click(await screen.findByRole("button", { name: "Calibrate" }));

    expect(screen.getByRole("dialog", { name: "Gantry calibration" })).toBeInTheDocument();
    expect(screen.getByText(/single-instrument deck origin/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /XY origin/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("button", { name: "Home gantry" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Home gantry" }));

    const blockHeight = await screen.findByLabelText("Reference height (mm)");
    expect(blockHeight).toHaveValue("35");
    expect(blockHeight).toBeEnabled();
    await user.clear(blockHeight);
    await user.type(blockHeight, "36.25");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    const setOrigin = await screen.findByRole("button", { name: "Set origin and continue" });
    expect(setOrigin).toBeInTheDocument();
    await waitFor(() => expect(setOrigin).toBeEnabled());
    expect(screen.queryByRole("button", { name: /Set XY origin/ })).not.toBeInTheDocument();
    expect(screen.queryByText("XY origin")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set Z reference/ })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/gantry/calibration/prepare-origin",
      expect.objectContaining({ method: "POST" }),
    );

    await user.click(setOrigin);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/gantry/work-coordinates",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ x: 0, y: 0, z: 36.25 }),
      }),
    ));
    expect(await screen.findByText("Origin set. Ready to measure and save.")).toBeInTheDocument();
    expect(screen.queryByText(/Program GRBL soft-limit travel spans/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Done" })).not.toBeInTheDocument();

    await user.click(within(screen.getByRole("dialog", { name: "Gantry calibration" })).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/gantry/calibration/finalize-origin",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          home_z: 80,
          block_touch_z: 0,
          block_height: 36.25,
          factory_z_travel: 80,
        }),
      }),
    ));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/gantry/cubos.yaml",
      expect.objectContaining({ method: "PUT" }),
    ));
    expect(state.gantries["cubos.yaml"]?.config.working_volume.z_max).toBe(80);
    expect(state.gantries["cubos.yaml"]?.config.grbl_settings?.max_travel_z).toBe(90);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Gantry calibration" })).not.toBeInTheDocument());
  });

  it("shows an error when block height is empty and Continue is clicked", async () => {
    const user = userEvent.setup();
    installFetchMock(createState());
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    await user.click(await screen.findByRole("button", { name: "Calibrate" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));

    const blockHeight = await screen.findByLabelText("Reference height (mm)");
    await user.clear(blockHeight);
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Enter a calibration reference height before continuing.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set origin and continue" })).not.toBeInTheDocument();
  });

  it("shows an error when block height is zero or negative and Continue is clicked", async () => {
    const user = userEvent.setup();
    installFetchMock(createState());
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    await user.click(await screen.findByRole("button", { name: "Calibrate" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));

    const blockHeight = await screen.findByLabelText("Reference height (mm)");
    await user.clear(blockHeight);
    await user.type(blockHeight, "0");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Calibration reference height must be greater than 0.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set origin and continue" })).not.toBeInTheDocument();
  });

  it("reconnects after saving calibrated output to a different gantry filename", async () => {
    const user = userEvent.setup();
    const state = createState();
    const fetchMock = installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    await user.click(await screen.findByRole("button", { name: "Calibrate" }));

    const outputYaml = screen.getByLabelText("Output YAML");
    await user.clear(outputYaml);
    await user.type(outputYaml, "calibrated.yaml");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Home gantry" }));
    await user.click(await screen.findByRole("button", { name: "Continue" }));
    const setOrigin = await screen.findByRole("button", { name: "Set origin and continue" });
    await waitFor(() => expect(setOrigin).toBeEnabled());
    await user.click(setOrigin);
    expect(await screen.findByText("Origin set. Ready to measure and save.")).toBeInTheDocument();
    await user.click(within(screen.getByRole("dialog", { name: "Gantry calibration" })).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/gantry/calibrated.yaml",
      expect.objectContaining({ method: "PUT" }),
    ));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/gantry/disconnect",
      expect.objectContaining({ method: "POST" }),
    ));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/gantry/connect",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ filename: "calibrated.yaml" }),
      }),
    ));
  });

  it("loads and saves a protocol config across tab switches", async () => {
    const user = userEvent.setup();
    const state = createState();
    installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    const travelZField = await screen.findByLabelText("Travel Z");
    expect(travelZField).toHaveValue("3");
    const parkYField = await screen.findByLabelText("park coordinates Y");
    expect(parkYField).toHaveValue("20");

    await user.clear(travelZField);
    await user.type(travelZField, "42");
    const positionField = screen.getByLabelText(/^Position \*$/);
    await user.clear(positionField);
    await user.type(positionField, "park");
    await user.clear(parkYField);
    await user.type(parkYField, "40");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(state.protocols["move.yaml"]?.positions).toEqual({ park: [10, 40, 30] }));
    expect(state.protocols["move.yaml"]?.steps[0].args.position).toBe("park");
    await user.click(screen.getByRole("button", { name: "Gantry" }));
    await user.click(screen.getByRole("button", { name: "Protocol" }));

    await waitFor(() => expect(screen.getByDisplayValue("42")).toBeInTheDocument());
    expect(screen.getByLabelText("park coordinates Y")).toHaveValue("40");
    expect(screen.getByLabelText(/^Position \*$/)).toHaveValue("park");
  });

  it("adds protocol named positions independently from protocol steps", async () => {
    const user = userEvent.setup();
    const state = createState();
    installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    await user.click(await screen.findByRole("button", { name: "Add Position" }));
    const nameField = await screen.findByLabelText("Position 2 name");

    await user.clear(nameField);
    await user.type(nameField, "staging_position");
    await user.clear(screen.getByLabelText("staging_position coordinates X"));
    await user.type(screen.getByLabelText("staging_position coordinates X"), "11");
    await user.clear(screen.getByLabelText("staging_position coordinates Y"));
    await user.type(screen.getByLabelText("staging_position coordinates Y"), "22");
    await user.clear(screen.getByLabelText("staging_position coordinates Z"));
    await user.type(screen.getByLabelText("staging_position coordinates Z"), "33");

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(state.protocols["move.yaml"]?.positions).toEqual({
        park: [10, 20, 30],
        staging_position: [11, 22, 33],
      });
    });
  });

  it("validates the selected setup through the full CubOS setup endpoint", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    await user.click(await screen.findByRole("button", { name: "Validate" }));

    await waitFor(() => expect(screen.getByText("Protocol is valid.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/protocol/validate-setup",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          gantry_file: "cubos.yaml",
          deck_file: "panda-deck.yaml",
          protocol_file: "move.yaml",
        }),
      }),
    );
  });

  it("clears stale validation and blocks Validate while protocol edits are unsaved", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    await user.click(await screen.findByRole("button", { name: "Validate" }));
    expect(await screen.findByText("Protocol is valid.")).toBeInTheDocument();

    const travelZField = await screen.findByLabelText("Travel Z");
    await user.clear(travelZField);
    await user.type(travelZField, "12");

    expect(screen.queryByText("Protocol is valid.")).not.toBeInTheDocument();

    const callsBeforeDirtyValidate = fetchMock.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Validate" }));

    expect(await screen.findByText("Save your changes first — Validate checks the saved files.")).toBeInTheDocument();
    const validateCallsAfterDirtyValidate = fetchMock.mock.calls
      .slice(callsBeforeDirtyValidate)
      .filter(([input]) => {
        const url = new URL(
          typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
          "http://localhost",
        );
        return url.pathname === "/api/protocol/validate-setup";
      });
    expect(validateCallsAfterDirtyValidate).toHaveLength(0);
  });

  it("surfaces Validate setup request failures", async () => {
    const user = userEvent.setup();
    installFetchMock(createState(), {
      validateSetup: () => new Response(JSON.stringify({ detail: "validator unavailable" }), {
        status: 500,
        statusText: "Internal Server Error",
        headers: { "Content-Type": "application/json" },
      }),
    });

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    await user.click(await screen.findByRole("button", { name: "Validate" }));

    expect(await screen.findByText("validator unavailable")).toBeInTheDocument();
  });

  it("guards Validate when no protocol file is selected", async () => {
    const user = userEvent.setup();

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await user.click(await screen.findByRole("button", { name: "Validate" }));

    expect(await screen.findByText("Select gantry, deck, and protocol files before setup validation.")).toBeInTheDocument();
  });

  it("surfaces saved-setup validation errors from CubOS", async () => {
    const user = userEvent.setup();
    installFetchMock(createState(), {
      validateSetup: () => jsonResponse({
        valid: false,
        errors: ["step 2: unknown position"],
      }),
    });

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    await user.click(await screen.findByRole("button", { name: "Validate" }));

    expect(await screen.findByText("step 2: unknown position")).toBeInTheDocument();
  });

  it("keeps Run Protocol disabled while the gantry is disconnected", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    const runButton = await screen.findByRole("button", { name: "Run Protocol" });

    expect(runButton).toBeDisabled();
    await user.click(runButton);
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/protocol/run",
      expect.anything(),
    );
  });

  it("disables Run Protocol and shows the calibration warning while connected", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock(createState(), {
      calibrationWarning: "Finish gantry calibration before running protocols.",
    });
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);
    await connectGantry(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");

    expect(await screen.findAllByText("Finish gantry calibration before running protocols.")).not.toHaveLength(0);
    const runButton = screen.getByRole("button", { name: "Run Protocol" });
    expect(runButton).toBeDisabled();
    await user.click(runButton);
    expect(fetchMock).not.toHaveBeenCalledWith("/api/protocol/run", expect.anything());
  });

  it("blocks Run Protocol after editing a loaded protocol until the change is saved", async () => {
    const user = userEvent.setup();
    const state = createState();
    const fetchMock = installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);
    await connectGantry(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");

    // Gantry is connected and nothing edited yet: Run is allowed.
    const runButton = await screen.findByRole("button", { name: "Run Protocol" });
    await waitFor(() => expect(runButton).toBeEnabled());

    // Editing a field marks the protocol dirty: Run must be blocked and
    // the user warned, and clicking it must not hit the run endpoint.
    const travelZField = await screen.findByLabelText("Travel Z");
    await user.clear(travelZField);
    await user.type(travelZField, "99");

    expect(await screen.findByText(/Unsaved changes/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled());
    await user.click(screen.getByRole("button", { name: "Run Protocol" }));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/protocol/run", expect.anything());

    // Saving clears the dirty state and re-enables running.
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(state.protocols["move.yaml"]?.steps[0].args.travel_z).toBe(99));
    await waitFor(() => expect(screen.queryByText(/Unsaved changes/i)).not.toBeInTheDocument());

    const runAfterSave = screen.getByRole("button", { name: "Run Protocol" });
    await waitFor(() => expect(runAfterSave).toBeEnabled());
    await user.click(runAfterSave);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/protocol/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          gantry_file: "cubos.yaml",
          deck_file: "panda-deck.yaml",
          protocol_file: "move.yaml",
        }),
      }),
    ));
    expect(await screen.findByText(/campaign #123 created/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Last Campaign")).toHaveValue("#123");
  });

  it("surfaces protocol run failures and re-enables Run Protocol", async () => {
    const user = userEvent.setup();
    installFetchMock(createState(), {
      protocolRun: async () => new Response("Gantry lost connection", {
        status: 500,
        statusText: "Internal Server Error",
      }),
    });

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);
    await connectGantry(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    await user.click(await screen.findByRole("button", { name: "Run Protocol" }));

    expect(await screen.findByText("Gantry lost connection")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Protocol" })).toBeEnabled());
    expect(screen.queryByRole("button", { name: "Running..." })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelling..." })).not.toBeInTheDocument();
  });

  it("keeps the run pending after cancel until the protocol request settles", async () => {
    const user = userEvent.setup();
    let resolveRun!: (response: Response) => void;
    let runSignal: AbortSignal | undefined;
    const fetchMock = installFetchMock(createState(), {
      protocolRun: (init?: RequestInit) => new Promise<Response>((resolve) => {
        runSignal = init?.signal ?? undefined;
        resolveRun = resolve;
      }),
      protocolCancel: () => jsonResponse({
        status: "cancel_requested",
        warning: "sent but not acknowledged",
      }),
    });
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);
    await connectGantry(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    await user.click(await screen.findByRole("button", { name: "Run Protocol" }));

    expect(await screen.findByRole("button", { name: "Running..." })).toBeDisabled();
    const cancelButton = await screen.findByRole("button", { name: "Cancel Run" });
    expect(cancelButton).toBeEnabled();

    await user.click(cancelButton);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/protocol/cancel",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(runSignal).toBeUndefined();
    expect(await screen.findAllByText(/sent but not acknowledged/i)).not.toHaveLength(0);
    expect(screen.getAllByRole("button", { name: "Cancelling..." }).every((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(screen.getByRole("button", { name: "Cancelling — waiting for protocol to stop" })).toBeDisabled();

    resolveRun(jsonResponse({ status: "complete", steps_executed: 1, campaign_id: 123 }));

    expect(await screen.findByText(/campaign #123 created/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelling — waiting for protocol to stop" })).not.toBeInTheDocument();
  });

  it("shows a protocol-running sidebar banner outside the Protocol tab", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock(createState(), {
      runStatus: () => ({ active: true, protocol_file: "move.yaml" }),
    });
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Deck" }));

    expect(await screen.findByText("● Protocol running…")).toBeInTheDocument();
    expect(screen.getByText("Protocol running — manual control locked")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/protocol/cancel",
      expect.objectContaining({ method: "POST" }),
    ));
  });

  it("blocks Run Protocol when an unsaved edit lives in another tab (Deck)", async () => {
    const user = userEvent.setup();
    const state = createState();
    const fetchMock = installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);
    await connectGantry(user);

    // Edit the deck but do NOT save it.
    await user.click(screen.getByRole("button", { name: "Deck" }));
    const deckNameField = await screen.findByDisplayValue("Deck Plate");
    await user.clear(deckNameField);
    await user.type(deckNameField, "Edited Plate");

    // The protocol itself is untouched, but Run executes the saved deck
    // file, so the unsaved deck edit must still block running.
    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/Unsaved changes/i);
    expect(banner).toHaveTextContent("Deck");
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled());
    await user.click(screen.getByRole("button", { name: "Run Protocol" }));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/protocol/run", expect.anything());
  });

  it("prompts to save deck edits in the Deck tab", async () => {
    const user = userEvent.setup();
    installFetchMock(createState());
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Deck" }));
    await importConfig(user, "Import deck config", "deck.yaml");
    const nameField = await screen.findByDisplayValue("Deck Plate");

    // No prompt before editing.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.clear(nameField);
    await user.type(nameField, "Renamed Plate");

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/Unsaved changes/i);
    expect(banner).toHaveTextContent(/save this deck/i);
  });

  it("prompts to save gantry edits and keeps GRBL under an Advanced settings expander", async () => {
    const user = userEvent.setup();
    installFetchMock(createState());
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    await screen.findByLabelText("Serial port");

    // GRBL fields are hidden until Advanced settings is expanded.
    expect(screen.queryByLabelText("Steps/mm X")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Advanced settings/ }));
    expect(await screen.findByLabelText("Steps/mm X")).toBeInTheDocument();

    // Editing prompts to save in this (Gantry) tab.
    await user.type(screen.getByLabelText("Serial port"), "/dev/ttyUSB9");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/Unsaved changes/i);
    expect(banner).toHaveTextContent(/save this gantry/i);
  });

  it("adds protocol steps with deck, instrument, method, and ASMI force-limit choices", async () => {
    const user = userEvent.setup();
    const state = createState();
    state.gantries["cubos.yaml"].config.instruments = {
      asmi: {
        type: "asmi",
        vendor: "vernier",
        offset_x: 1,
        offset_y: 2,
        depth: 0,
      },
    };
    installFetchMock(state);

    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    expect(screen.getByText("Load a protocol or add steps.")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Add step" }), "scan");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByLabelText(/Plate/)).toHaveValue("plate_1");
    expect(screen.getByLabelText(/Instrument/)).toHaveValue("asmi");
    expect(screen.getByLabelText(/^Measurement \*$/)).toHaveValue("indentation");
    expect(screen.getByLabelText("Force limit (N)")).toHaveValue("10");
  });

  it("guards discarding unsaved deck edits when switching the imported file", async () => {
    const user = userEvent.setup();
    const state = createState();
    state.decks["deck2.yaml"] = {
      filename: "deck2.yaml",
      labware: [
        {
          key: "plate_2",
          config: { ...state.decks["deck.yaml"].labware[0].config, name: "Second Deck Plate" },
          wells: null,
        },
      ],
    };
    installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();

    await user.click(screen.getByRole("button", { name: "Deck" }));
    await importConfig(user, "Import deck config", "deck.yaml");
    const nameField = await screen.findByDisplayValue("Deck Plate");
    await user.clear(nameField);
    await user.type(nameField, "Edited Plate");

    // Cancelling the confirm keeps the edits and the current file.
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await importConfig(user, "Import deck config", "deck2.yaml");
    expect(confirmSpy).toHaveBeenCalled();
    expect(confirmSpy.mock.calls[0][0]).toContain("panda-deck.yaml");
    expect(screen.getByDisplayValue("Edited Plate")).toBeInTheDocument();

    // Confirming discards the edit and switches to the newly imported file.
    confirmSpy.mockReturnValueOnce(true);
    await importConfig(user, "Import deck config", "deck2.yaml");
    expect(await screen.findByDisplayValue("Second Deck Plate")).toBeInTheDocument();

    confirmSpy.mockRestore();
  });

  it("guards discarding unsaved gantry edits when switching the imported file", async () => {
    const user = userEvent.setup();
    const state = createState();
    state.gantries["cubos2.yaml"] = {
      filename: "cubos2.yaml",
      config: { ...state.gantries["cubos.yaml"].config, serial_port: "/dev/ttyUSB-second" },
    };
    installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();

    await importConfig(user, "Import gantry config", "cubos.yaml");
    const serialPort = await screen.findByLabelText("Serial port");
    await user.type(serialPort, "-edited");

    // Cancelling the confirm keeps the edits and the current file. (The
    // field now shows a per-field amber "*" since it differs from the
    // saved baseline, so match loosely.)
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await importConfig(user, "Import gantry config", "cubos2.yaml");
    expect(confirmSpy).toHaveBeenCalled();
    expect(screen.getByLabelText(/^Serial port/)).toHaveValue("-edited");

    // Confirming discards the edit and switches to the newly imported file.
    confirmSpy.mockReturnValueOnce(true);
    await importConfig(user, "Import gantry config", "cubos2.yaml");
    await waitFor(() => expect(screen.getByLabelText("Serial port")).toHaveValue("/dev/ttyUSB-second"));

    confirmSpy.mockRestore();
  });

  it("guards discarding unsaved protocol edits when switching the imported file", async () => {
    const user = userEvent.setup();
    const state = createState();
    state.protocols["move2.yaml"] = {
      filename: "move2.yaml",
      positions: { staging: [5, 5, 5] },
      steps: [{ command: "move", args: { instrument: "pipette_1", position: "plate_1.A1", travel_z: 9 } }],
    };
    installFetchMock(state);
    renderApp();
    await waitForSettingsLoad();
    await loadRequiredProtocolDependencies(user);

    await user.click(screen.getByRole("button", { name: "Protocol" }));
    await importConfig(user, "Import protocol config", "move.yaml");
    const travelZField = await screen.findByLabelText("Travel Z");
    await user.clear(travelZField);
    await user.type(travelZField, "77");

    // Cancelling the confirm keeps the edits and the current file.
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await importConfig(user, "Import protocol config", "move2.yaml");
    expect(confirmSpy).toHaveBeenCalled();
    expect(screen.getByLabelText("Travel Z")).toHaveValue("77");

    // Confirming discards the edit and switches to the newly imported file.
    confirmSpy.mockReturnValueOnce(true);
    await importConfig(user, "Import protocol config", "move2.yaml");
    await waitFor(() => expect(screen.getByLabelText("Travel Z")).toHaveValue("9"));

    confirmSpy.mockRestore();
  });

  it("guards page unload while any editor has unsaved edits", async () => {
    const user = userEvent.setup();
    installFetchMock(createState());
    renderApp();
    await waitForSettingsLoad();

    const cleanEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanEvent);
    expect(cleanEvent.defaultPrevented).toBe(false);

    await user.click(screen.getByRole("button", { name: "Deck" }));
    await importConfig(user, "Import deck config", "deck.yaml");
    const nameField = await screen.findByDisplayValue("Deck Plate");
    await user.type(nameField, "!");

    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());

    const afterSaveEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(afterSaveEvent);
    expect(afterSaveEvent.defaultPrevented).toBe(false);
  });
});
