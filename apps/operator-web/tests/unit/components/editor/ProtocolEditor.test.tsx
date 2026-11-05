import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ProtocolEditor from "../../../../src/components/editor/ProtocolEditor";
import { stepToYaml, stepsFromYaml, createRepeatBlock } from "../../../../src/components/editor/protocolRepeat";
import type { CommandInfo, DeckResponse, GantryResponse, ProtocolResponse, ProtocolStep } from "../../../../src/types";

const COMMANDS: CommandInfo[] = [
  {
    name: "move",
    description: "Move",
    args: [
      { name: "instrument", type: "str", required: true, default: null },
      { name: "position", type: "Any", required: true, default: null },
      { name: "travel_z", type: "float | None", required: false, default: null },
    ],
  },
  {
    name: "scan",
    description: "Scan",
    args: [
      { name: "plate", type: "str", required: true, default: null },
      { name: "instrument", type: "str", required: true, default: null },
      { name: "method", type: "str", required: true, default: null },
      { name: "measurement_height", type: "float", required: true, default: null },
      { name: "indentation_limit_height", type: "float | None", required: false, default: null },
      { name: "method_kwargs", type: "Dict[str, Any] | None", required: false, default: null },
    ],
  },
  {
    name: "measure",
    description: "Measure",
    args: [
      { name: "instrument", type: "str", required: true, default: null },
      { name: "position", type: "str", required: true, default: null },
      { name: "method", type: "str", required: false, default: "measure" },
      { name: "measurement_height", type: "float", required: true, default: null },
      { name: "indentation_limit_height", type: "float | None", required: false, default: null },
      { name: "method_kwargs", type: "Dict[str, Any] | None", required: false, default: null },
    ],
  },
];

const DECK: DeckResponse = {
  filename: "deck.yaml",
  labware: [
    {
      key: "plate_1",
      config: {
        type: "well_plate",
        name: "Plate",
        model_name: "m",
        rows: 2,
        columns: 2,
        length: 100,
        width: 80,
        height: 14,
        calibration: { a1: { x: 0, y: 0, z: 0 }, a2: { x: 9, y: 0, z: 0 } },
        x_offset: 9,
        y_offset: 9,
        capacity_ul: 200,
        working_volume_ul: 150,
      },
      wells: null,
    },
  ],
};

const GANTRY: GantryResponse = {
  filename: "g.yaml",
  config: {
    serial_port: "",
    gantry_type: "cub_xl",
    cnc: { factory_z_travel_mm: 80, y_axis_motion: "head", safe_z: 80 },
    working_volume: { x_min: 0, x_max: 300, y_min: 0, y_max: 200, z_min: 0, z_max: 80 },
    grbl_settings: {},
    instruments: {
      asmi: { type: "asmi", vendor: "vernier", offset_x: 0, offset_y: 0 },
      uv_curing: { type: "uv_curing", vendor: "mock", offset_x: 0, offset_y: 0 },
      pip: { type: "pipette", vendor: "opentrons", offset_x: 0, offset_y: 0 },
    },
  },
};

const STEPS: ProtocolStep[] = [
  { command: "move", args: { instrument: "asmi", position: "plate_1.A1", travel_z: 3 } },
];

function renderProtocol(overrides: Partial<React.ComponentProps<typeof ProtocolEditor>> = {}) {
  const props: React.ComponentProps<typeof ProtocolEditor> = {
    configs: ["move.yaml"],
    selectedFile: "move.yaml",
    onSelectFile: vi.fn(),
    onImportFile: vi.fn(),
    commands: COMMANDS,
    deck: DECK,
    gantry: GANTRY,
    steps: STEPS,
    positions: null,
    baseline: null,
    onSave: vi.fn(),
    onLocalChange: vi.fn(),
    onPositionsChange: vi.fn(),
    onValidate: vi.fn(),
    validationErrors: null,
    isValidating: false,
    onRefresh: vi.fn(),
    onRun: vi.fn(),
    onCancelRun: vi.fn(),
    unsavedConfigs: [],
    canRun: true,
    isRunning: false,
    isCancelingRun: false,
    runResult: null,
    runError: null,
    ...overrides,
  };
  render(<ProtocolEditor {...props} />);
  return props;
}

describe("ProtocolEditor", () => {
  it("selects plate wells, preserves them when minimized, and builds only selected targets", async () => {
    const user = userEvent.setup();
    const wells = Object.fromEntries(["A1", "A2", "B1", "B2"].map(w => [w, { x: 0, y: 0, z: 0 }]));
    const props = renderProtocol({ deck: { ...DECK, labware: [{ ...DECK.labware[0], wells }] } });
    expect(screen.queryByRole("group", { name: "Target well plate" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Add repeat/ }));
    await user.click(screen.getByRole("button", { name: "Clear" }));
    await user.click(screen.getByRole("button", { name: "Row B" }));
    await user.click(screen.getByRole("button", { name: "Repeat target B1" }));
    expect(screen.getByRole("button", { name: "Repeat target B2" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: /Minimize/ }));
    expect(screen.queryByRole("group", { name: "Target well plate" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Expand/ }));
    expect(screen.getByRole("button", { name: "Repeat target B2" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Create repeat" }));
    expect(props.onLocalChange).toHaveBeenLastCalledWith([
      { command: "repeat", args: { labware: "plate_1", template_well: "A1", wells: ["B2"], steps: STEPS } },
    ]);
    expect(screen.getByRole("button", { name: /Add repeat/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("retains a native repeat through raw YAML, child edits, and saving", async () => {
    const user = userEvent.setup();
    const wells = Object.fromEntries(["A1", "A2"].map(w => [w, { x: 0, y: 0, z: 0 }]));
    const repeat = { command: "repeat", args: { labware: "plate_1", template_well: "A1", wells: ["A1", "A2"], steps: STEPS } };
    const props = renderProtocol({ steps: [repeat], deck: { ...DECK, labware: [{ ...DECK.labware[0], wells }] } });
    const block = screen.getByRole("region", { name: "Repeat block 1" });
    await user.click(within(block).getByRole("button", { name: "Repeat target A2" }));
    const travel = within(block).getByLabelText(/Travel Z/i);
    fireEvent.change(travel, { target: { value: "7" } });
    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));
    expect((screen.getByLabelText("Raw YAML") as HTMLTextAreaElement).value).toContain("repeat:");
    expect((screen.getByLabelText("Raw YAML") as HTMLTextAreaElement).value).toContain("travel_z: 7");
    await user.click(screen.getByRole("button", { name: "Apply to form" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(props.onSave).toHaveBeenCalledWith("move.yaml", { protocol: [{ command: "repeat", args: {
      labware: "plate_1", template_well: "A1", wells: ["A1"], steps: [{ command: "move", args: { instrument: "asmi", position: "plate_1.A1", travel_z: 7 } }],
    } }] });
  });

  it("edits a repeat plate and adds and removes child steps without flattening", async () => {
    const user = userEvent.setup();
    const repeat = { command: "repeat", args: { labware: "plate_1", template_well: "A1", wells: ["A1"], steps: STEPS } };
    const props = renderProtocol({ steps: [repeat], deck: { ...DECK, labware: [
      { ...DECK.labware[0], wells: { A1: { x: 0, y: 0, z: 0 } } },
      { ...DECK.labware[0], key: "plate_2", wells: { B2: { x: 1, y: 1, z: 0 } } },
    ] } });
    await user.click(screen.getByRole("button", { name: "Use plate_2 for repeat 1" }));
    expect(props.onLocalChange).toHaveBeenLastCalledWith([{ command: "repeat", args: {
      labware: "plate_2", template_well: "B2", wells: ["B2"], steps: [{ ...STEPS[0], args: { ...STEPS[0].args, position: "plate_2.B2" } }],
    } }]);
    await user.click(screen.getByRole("button", { name: "Add step to repeat" }));
    expect(screen.getByRole("button", { name: "Remove repeat 1 step 2" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove repeat 1 step 2" }));
    expect(screen.queryByRole("button", { name: "Remove repeat 1 step 2" })).not.toBeInTheDocument();
    expect(props.onLocalChange).toHaveBeenLastCalledWith([{ command: "repeat", args: {
      labware: "plate_2", template_well: "B2", wells: ["B2"], steps: [{ ...STEPS[0], args: { ...STEPS[0].args, position: "plate_2.B2" } }],
    } }]);
  });

  it("round trips native YAML and rejects nested repeat creation", () => {
    const steps = createRepeatBlock(STEPS, 1, 1, "plate_1", "A1", ["A1", "A2"]);
    expect(stepsFromYaml(steps.map(stepToYaml))).toEqual(steps);
    expect(() => createRepeatBlock(steps, 1, 1, "plate_1", "A1", ["A1"])).toThrow("cannot contain another repeat");
    expect(() => stepsFromYaml([{ repeat: { labware: "plate_1", template_well: "A1", wells: ["A1"], steps: steps.map(stepToYaml) } }])).toThrow("cannot contain another repeat");
  });

  it("switches visual plates and supports column selection", async () => {
    const user = userEvent.setup();
    const wells = Object.fromEntries(["A1", "A2", "B1", "B2"].map(w => [w, { x: 0, y: 0, z: 0 }]));
    renderProtocol({ deck: { ...DECK, labware: [
      { ...DECK.labware[0], wells }, { ...DECK.labware[0], key: "plate_2", wells: { C3: { x: 0, y: 0, z: 0 } } },
    ] } });
    await user.click(screen.getByRole("button", { name: /Add repeat/ }));
    await user.click(screen.getByRole("button", { name: "Column 2" }));
    expect(screen.getByRole("button", { name: "Repeat target A2" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Repeat target B2" })).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "Use plate_2" }));
    expect(screen.getByLabelText("Template well")).toHaveValue("C3");
    expect(screen.getByRole("button", { name: "Repeat target C3" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Repeat target A1" })).not.toBeInTheDocument();
  });

  it("groups only the selected child steps while retaining surrounding tip steps", () => {
    const input = [
      { command: "pick_up_tip", args: { position: "tips" } },
      { command: "dispense", args: { position: "plate_1.A1", volume_ul: 10 } },
      { command: "drop_tip", args: { position: "waste" } },
    ];
    const grouped = createRepeatBlock(input, 2, 2, "plate_1", "A1", ["A1", "A2"]);
    expect(grouped.map(step => step.command)).toEqual(["pick_up_tip", "repeat", "drop_tip"]);
    expect(grouped[1].args.steps).toEqual([input[1]]);
    expect(grouped[1].args.wells).toEqual(["A1", "A2"]);
    expect(input[1].command).toBe("dispense");
  });

  it("adds Rinse with a potentiostat and vial choices and saves the selected depth", async () => {
    const user = userEvent.setup();
    const rinse: CommandInfo = {
      name: "rinse", description: "Dip the potentiostat three times",
      args: [
        { name: "instrument", type: "str", required: true, default: null },
        { name: "vial", type: "str", required: true, default: null },
        { name: "measurement_height", type: "float", required: true, default: null },
      ],
    };
    const props = renderProtocol({
      commands: [...COMMANDS, rinse], steps: [],
      gantry: { ...GANTRY, config: { ...GANTRY.config, instruments: {
        ...GANTRY.config.instruments,
        pstat: { type: "potentiostat", vendor: "mock", offset_x: 0, offset_y: 0 },
      } } },
      deck: { ...DECK, labware: [...DECK.labware, {
        key: "rinse_vial", wells: null,
        config: { type: "vial", name: "Rinse water", model_name: "4ml", height: 30, diameter: 10, location: { x: 10, y: 10, z: 20 }, capacity_ul: 4000, working_volume_ul: 3000 },
      }, {
        key: "holder", wells: null,
        config: { type: "vial_holder", name: "Rinse holder" },
        positions: { vial_1: { x: 30, y: 10, z: 20 } },
      }] },
    });
    await user.selectOptions(screen.getByRole("combobox", { name: "Add step" }), "rinse");
    await user.click(screen.getByRole("button", { name: "Add" }));
    const instrument = screen.getByRole("combobox", { name: /Instrument/ });
    expect(instrument).toHaveValue("pstat");
    expect(instrument.querySelectorAll("option")).toHaveLength(1);
    const vial = screen.getByRole("combobox", { name: /Vial/ });
    expect(vial).toHaveValue("rinse_vial");
    expect(vial.querySelectorAll("option")).toHaveLength(2);
    await user.selectOptions(vial, "holder.vial_1");
    fireEvent.change(screen.getByLabelText(/Measurement height/), { target: { value: "-5" } });
    expect(props.onLocalChange).toHaveBeenLastCalledWith([
      { command: "rinse", args: { instrument: "pstat", vial: "holder.vial_1", measurement_height: -5 } },
    ]);
  });

  it("shows the empty state when no steps are loaded", () => {
    renderProtocol({ steps: null });
    expect(screen.getByText("Load a protocol or add steps.")).toBeInTheDocument();
    // The action bar itself always renders (so Discard stays reachable
    // and the user isn't stranded), but Run/Save are disabled with a hint.
    expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText(/Add at least one step/i)).toBeInTheDocument();
  });

  it("prompts to save the protocol itself and marks the Save button when protocol is dirty", () => {
    renderProtocol({ unsavedConfigs: ["Protocol"] });
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent(/Save this protocol before running/i);
    // Save button keeps the accessible name "Save" with an aria-hidden "*".
    expect(screen.getByRole("button", { name: "Save" })).toHaveTextContent("*");
    expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled();
  });

  it("points to another tab when only the deck is dirty", () => {
    renderProtocol({ unsavedConfigs: ["Deck"] });
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent(/Deck has unsaved edits/i);
    expect(banner).toHaveTextContent(/save it in the Deck tab/i);
    // The protocol's own Save button is not marked dirty.
    expect(screen.getByRole("button", { name: "Save" })).not.toHaveTextContent("*");
  });

  it("pluralizes the pointer when multiple other tabs are dirty", () => {
    renderProtocol({ unsavedConfigs: ["Gantry", "Deck"] });
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent(/have unsaved edits/i);
    expect(banner).toHaveTextContent(/save them in their tabs/i);
  });

  it("runs when nothing is dirty and the gantry can run", async () => {
    const user = userEvent.setup();
    const props = renderProtocol();
    const runButton = screen.getByRole("button", { name: "Run Protocol" });
    expect(runButton).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(runButton);
    expect(props.onRun).toHaveBeenCalled();
  });

  it("keeps the running state visible and shows a cancel button while running", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({ isRunning: true });

    expect(screen.getByRole("button", { name: "Running..." })).toBeDisabled();
    const cancelButton = screen.getByRole("button", { name: "Cancel Run" });
    expect(cancelButton).toBeEnabled();
    const buttonLabels = screen.getAllByRole("button").map((button) => button.textContent);
    expect(buttonLabels.indexOf("Cancel Run")).toBeLessThan(buttonLabels.indexOf("Running..."));

    await user.click(cancelButton);
    expect(props.onCancelRun).toHaveBeenCalled();
  });

  it("disables the cancel button while cancellation is being requested", () => {
    renderProtocol({ isRunning: true, isCancelingRun: true });
    expect(screen.queryByRole("button", { name: "Running..." })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelling..." })).toBeDisabled();
  });

  it("disables Run while the gantry cannot run", () => {
    renderProtocol({ canRun: false });
    expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled();
  });

  it("validates the current config", async () => {
    const user = userEvent.setup();
    const props = renderProtocol();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(props.onValidate).toHaveBeenCalledWith(
      expect.objectContaining({ protocol: expect.any(Array) }),
    );
  });

  it("matches step validation errors exactly and displays legacy indices as 1-based", () => {
    const manySteps = Array.from({ length: 11 }, () => STEPS[0]);
    renderProtocol({
      steps: manySteps,
      validationErrors: [
        "Step 1 (move): second-card problem",
        "Step 10 (move): eleventh-card problem",
      ],
    });

    expect(screen.getAllByText("Step 2 (move): second-card problem")).toHaveLength(2);
    expect(screen.getAllByText("Step 11 (move): eleventh-card problem")).toHaveLength(2);
    expect(screen.queryByText("Step 10 (move): eleventh-card problem")).not.toBeInTheDocument();
  });

  it("adds, reorders, and removes steps", async () => {
    const user = userEvent.setup();
    const props = renderProtocol();
    const moveStep = STEPS[0];
    const scanStep = {
      command: "scan",
      args: {
        plate: "plate_1",
        instrument: "asmi",
        method: "indentation",
        measurement_height: 0,
        method_kwargs: {
          step_size: 0.1,
          force_limit: 10,
          baseline_samples: 10,
          measure_with_return: false,
        },
      },
    };

    await user.selectOptions(screen.getByRole("combobox", { name: "Add step" }), "scan");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(props.onLocalChange).toHaveBeenCalled();

    // Two steps now → the first step's down-arrow becomes actionable.
    // Buttons are labelled by their glyph (↓ / ✕), not the title.
    await user.click(screen.getAllByRole("button", { name: "↓" })[0]);
    await user.click(screen.getAllByRole("button", { name: "✕" })[0]);
    expect(props.onLocalChange).toHaveBeenNthCalledWith(2, [scanStep, moveStep]);
    expect(props.onLocalChange).toHaveBeenNthCalledWith(3, [moveStep]);
  });

  it("adds and removes named positions", async () => {
    const user = userEvent.setup();
    const props = renderProtocol();

    await user.click(screen.getByRole("button", { name: "Add Position" }));
    expect(props.onPositionsChange).toHaveBeenCalled();

    const nameField = await screen.findByLabelText("Position 1 name");
    await user.clear(nameField);
    await user.type(nameField, "park");
    await user.click(screen.getByRole("button", { name: /Remove park/i }));
    // Last call clears positions back to null.
    expect(props.onPositionsChange).toHaveBeenLastCalledWith(null);
  });

  it("exposes ASMI indentation method options for an asmi scan step", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({ steps: [] });

    await user.selectOptions(screen.getByRole("combobox", { name: "Add step" }), "scan");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // asmi is the first instrument and "indentation" its default method, so
    // the ASMI method-options grid renders.
    expect(await screen.findByLabelText("Force limit (N)")).toHaveValue("10");
    await user.clear(screen.getByLabelText("Force limit (N)"));
    await user.type(screen.getByLabelText("Force limit (N)"), "12");
    expect(props.onLocalChange).toHaveBeenCalled();
  });

  it("hides surface detection params until detect surface is enabled", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({ steps: [] });

    await user.selectOptions(screen.getByRole("combobox", { name: "Add step" }), "scan");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // Surface-search parameters are irrelevant noise while detection is off,
    // so they should be absent from the DOM entirely, not just disabled.
    expect(await screen.findByLabelText("Detect surface")).toHaveValue("false");
    expect(screen.queryByLabelText("Surface search step (mm)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Surface force threshold (N)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Surface search max travel (mm)")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Detect surface"), "true");

    expect(screen.getByLabelText("Surface search step (mm)")).toHaveValue("0.5");
    expect(screen.getByLabelText("Surface force threshold (N)")).toHaveValue("0.01");
    expect(screen.getByLabelText("Surface search max travel (mm)")).toHaveValue("10");
    expect(screen.getByLabelText("Surface search step (mm)")).toBeEnabled();
    expect(screen.getByLabelText("Surface force threshold (N)")).toBeEnabled();
    expect(screen.getByLabelText("Surface search max travel (mm)")).toBeEnabled();
    expect(props.onLocalChange).toHaveBeenLastCalledWith([
      expect.objectContaining({
        args: expect.objectContaining({
          method_kwargs: expect.objectContaining({
            detect_surface: true,
            surface_search_step: 0.5,
            surface_force_threshold: 0.01,
            surface_search_max_travel: 10,
          }),
        }),
      }),
    ]);

    await user.selectOptions(screen.getByLabelText("Detect surface"), "false");

    expect(screen.queryByLabelText("Surface search step (mm)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Surface force threshold (N)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Surface search max travel (mm)")).not.toBeInTheDocument();
  });

  it("strips surface detection params when detect surface is disabled", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({
      steps: [
        {
          command: "scan",
          args: {
            plate: "plate_1",
            instrument: "asmi",
            method: "indentation",
            measurement_height: -1,
            interwell_scan_height: 8,
            indentation_limit_height: -1,
            method_kwargs: {
              step_size: 0.02,
              force_limit: 10,
              detect_surface: true,
              surface_search_step: 0.5,
              surface_force_threshold: 0.01,
              surface_search_max_travel: 8,
            },
          },
        },
      ],
    });

    expect(screen.getByLabelText("Detect surface")).toHaveValue("true");
    expect(screen.getByLabelText("Surface search step (mm)")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Detect surface"), "false");

    expect(props.onLocalChange).toHaveBeenLastCalledWith([
      expect.objectContaining({
        args: expect.objectContaining({
          method_kwargs: {
            step_size: 0.02,
            force_limit: 10,
          },
        }),
      }),
    ]);
    expect(screen.queryByLabelText("Surface search step (mm)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Surface force threshold (N)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Surface search max travel (mm)")).not.toBeInTheDocument();
  });

  it("uses the CubOS-provided instrument method map before the fallback map", async () => {
    const user = userEvent.setup();
    renderProtocol({
      steps: [],
      instrumentMethods: {
        asmi: ["measure"],
      },
    });

    await user.selectOptions(screen.getByRole("combobox", { name: "Add step" }), "scan");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByLabelText(/^Measurement \*$/)).toHaveValue("measure");
    expect(screen.queryByLabelText("Force limit (N)")).not.toBeInTheDocument();
  });

  it("hides ASMI-only indentation limit for uv curing measure steps", () => {
    renderProtocol({
      steps: [
        {
          command: "measure",
          args: {
            instrument: "uv_curing",
            position: "plate_1.A1",
            method: "measure",
            measurement_height: 1,
          },
        },
      ],
    });

    expect(screen.getByLabelText(/Instrument/)).toHaveValue("uv_curing");
    expect(screen.getByLabelText(/^Measurement$/)).toHaveValue("measure");
    expect(screen.getByLabelText(/Measurement height/)).toHaveValue("1");
    expect(screen.queryByLabelText(/Indentation limit height/)).not.toBeInTheDocument();
    expect(screen.queryByText("ASMI indentation options")).not.toBeInTheDocument();
  });

  it("removes stale ASMI indentation args when switching to uv curing", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({
      steps: [
        {
          command: "measure",
          args: {
            instrument: "asmi",
            position: "plate_1.A1",
            method: "indentation",
            measurement_height: -1,
            indentation_limit_height: -5,
            method_kwargs: { force_limit: 10 },
          },
        },
      ],
    });

    expect(screen.getByLabelText(/Indentation limit height/)).toHaveValue("-5");
    await user.selectOptions(screen.getByRole("combobox", { name: /Instrument/ }), "uv_curing");

    expect(props.onLocalChange).toHaveBeenLastCalledWith([
      {
        command: "measure",
        args: {
          instrument: "uv_curing",
          position: "plate_1.A1",
          method: "measure",
          measurement_height: -1,
        },
      },
    ]);
  });

  it("does not inject a method arg into commands that do not declare one", async () => {
    const user = userEvent.setup();
    const decap: CommandInfo = {
      name: "decap",
      description: "Decap",
      args: [
        { name: "instrument", type: "str", required: true, default: null },
        { name: "vial", type: "str", required: true, default: null },
      ],
    };
    const props = renderProtocol({
      commands: [...COMMANDS, decap],
      gantry: {
        ...GANTRY,
        config: {
          ...GANTRY.config,
          instruments: {
            ...GANTRY.config.instruments,
            capper: { type: "capper", vendor: "pawduino", offset_x: 0, offset_y: 0 },
          },
        },
      },
      steps: [{ command: "decap", args: { instrument: "asmi", vial: "plate_1.A1" } }],
    });

    await user.selectOptions(screen.getByRole("combobox", { name: /Instrument/ }), "capper");

    expect(props.onLocalChange).toHaveBeenLastCalledWith([
      { command: "decap", args: { instrument: "capper", vial: "plate_1.A1" } },
    ]);
  });

  it("omits indentation_limit_height instead of saving an empty string when cleared, for measure", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({
      steps: [
        {
          command: "measure",
          args: {
            instrument: "asmi",
            position: "plate_1.A1",
            method: "indentation",
            measurement_height: -1,
            indentation_limit_height: -5,
            method_kwargs: { force_limit: 10 },
          },
        },
      ],
    });

    const field = screen.getByLabelText(/Indentation limit height/);
    expect(field).toHaveValue("-5");
    await user.clear(field);

    const calls = vi.mocked(props.onLocalChange!).mock.calls;
    const lastCall = calls[calls.length - 1][0];
    expect(lastCall[0].args).not.toHaveProperty("indentation_limit_height");
  });

  it("omits indentation_limit_height instead of saving an empty string when cleared, for scan", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({
      steps: [
        {
          command: "scan",
          args: {
            plate: "plate_1",
            instrument: "asmi",
            method: "indentation",
            measurement_height: -1,
            indentation_limit_height: -5,
            method_kwargs: { force_limit: 10 },
          },
        },
      ],
    });

    const field = screen.getByLabelText(/Indentation limit height/);
    expect(field).toHaveValue("-5");
    await user.clear(field);

    const calls = vi.mocked(props.onLocalChange!).mock.calls;
    const lastCall = calls[calls.length - 1][0];
    expect(lastCall[0].args).not.toHaveProperty("indentation_limit_height");
  });

  it("saves a newly entered indentation_limit_height as a number", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({
      steps: [
        {
          command: "measure",
          args: {
            instrument: "asmi",
            position: "plate_1.A1",
            method: "indentation",
            measurement_height: -1,
            method_kwargs: { force_limit: 10 },
          },
        },
      ],
    });

    const field = screen.getByLabelText(/Indentation limit height/);
    expect(field).toHaveValue("");
    await user.type(field, "-2.5");

    const calls = vi.mocked(props.onLocalChange!).mock.calls;
    const lastCall = calls[calls.length - 1][0];
    expect(lastCall[0].args.indentation_limit_height).toBe(-2.5);
  });

  it("renames a named position and rewrites the steps that reference it", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({
      steps: [{ command: "move", args: { instrument: "asmi", position: "park", travel_z: 1 } }],
      positions: { park: [1, 2, 3] },
    });

    // Append (don't clear) so "park" -> "park2" is a single rename that
    // can be propagated into the referencing step.
    await user.type(screen.getByLabelText("Position 1 name"), "2");
    expect(props.onLocalChange).toHaveBeenLastCalledWith([
      {
        command: "move",
        args: expect.objectContaining({ position: "park2" }),
      },
    ]);
    expect(props.onPositionsChange).toHaveBeenLastCalledWith({ park2: [1, 2, 3] });
  });

  it("renders run results and errors", () => {
    const { unmount } = render(
      <ProtocolEditor {...baseProps()} runResult={{ status: "complete", steps_executed: 2, campaign_id: 7 }} />,
    );
    expect(screen.getByText(/2 steps executed/i)).toBeInTheDocument();
    expect(screen.getByText(/campaign #7 created/i)).toBeInTheDocument();
    unmount();

    render(<ProtocolEditor {...baseProps()} runError="boom" />);
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("shows a save-failed banner and clears it on the next edit or successful save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn()
      .mockRejectedValueOnce(new Error("400: bad protocol"))
      .mockResolvedValueOnce(undefined);
    renderProtocol({ onSave });

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Save failed/i)).toHaveTextContent("400: bad protocol");

    // Editing again clears the stale error even before the retry.
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.queryByText(/Save failed/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/Save failed/i)).not.toBeInTheDocument();
  });

  it("discards local edits back to the last-saved baseline and notifies the parent", async () => {
    const user = userEvent.setup();
    const baseline: ProtocolResponse = { filename: "move.yaml", steps: STEPS, positions: null };
    const onRefresh = vi.fn();
    renderProtocol({ unsavedConfigs: ["Protocol"], baseline, onRefresh });

    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("Discard unsaved protocol changes?");
    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(onRefresh).toHaveBeenCalled();
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(1);
  });

  it("keeps edits when the user cancels the discard confirm", async () => {
    const user = userEvent.setup();
    const baseline: ProtocolResponse = { filename: "move.yaml", steps: STEPS, positions: null };
    const onRefresh = vi.fn();
    renderProtocol({ unsavedConfigs: ["Protocol"], baseline, onRefresh });

    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(2);
  });

  // ── Feature 07b: per-container starting-volume seed rows ──

  it("shows the starting-volumes editor only for the New fluid state choice", () => {
    const onFluidStateChoiceChange = vi.fn();
    const { rerender } = render(
      <ProtocolEditor
        {...baseProps()}
        onFluidStateChoiceChange={onFluidStateChoiceChange}
        fluidStateChoice={{ mode: "none", newLabel: "", resumeId: null, seeds: [] }}
      />,
    );
    expect(screen.queryByText("Starting volumes")).not.toBeInTheDocument();

    rerender(
      <ProtocolEditor
        {...baseProps()}
        onFluidStateChoiceChange={onFluidStateChoiceChange}
        fluidStateChoice={{ mode: "new", newLabel: "", resumeId: null, seeds: [] }}
      />,
    );
    expect(screen.getByText("Starting volumes")).toBeInTheDocument();
    expect(screen.getByText(/every container starts empty/i)).toBeInTheDocument();
  });

  it("adds a seed row through the choice callback", async () => {
    const user = userEvent.setup();
    const onFluidStateChoiceChange = vi.fn();
    render(
      <ProtocolEditor
        {...baseProps()}
        onFluidStateChoiceChange={onFluidStateChoiceChange}
        fluidStateChoice={{ mode: "new", newLabel: "", resumeId: null, seeds: [] }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Add container" }));
    expect(onFluidStateChoiceChange).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "new",
        seeds: [expect.objectContaining({ container: "", volume: "", composition: [] })],
      }),
    );
  });

  it("blocks Run and shows an inline error when a composition does not sum to the volume", () => {
    render(
      <ProtocolEditor
        {...baseProps()}
        onFluidStateChoiceChange={vi.fn()}
        fluidStateChoice={{
          mode: "new",
          newLabel: "",
          resumeId: null,
          seeds: [
            {
              id: "seed-a",
              container: "s1",
              volume: "100",
              composition: [{ id: "comp-a", component: "water", volume: "40" }],
            },
          ],
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/composition sums to 40/i);
    expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled();
  });

  it("enables Run when seed rows are valid", () => {
    render(
      <ProtocolEditor
        {...baseProps()}
        onFluidStateChoiceChange={vi.fn()}
        fluidStateChoice={{
          mode: "new",
          newLabel: "seeded",
          resumeId: null,
          seeds: [{ id: "seed-a", container: "s1", volume: "6500", composition: [] }],
        }}
      />,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Protocol" })).toBeEnabled();
  });
});

describe("ProtocolEditor raw YAML panel", () => {
  it("shows the current protocol as YAML text alongside the structured form", async () => {
    const user = userEvent.setup();
    renderProtocol({
      steps: STEPS,
      positions: { park_position: [360, 250, 85] },
    });

    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));

    const textarea = screen.getByLabelText("Raw YAML") as HTMLTextAreaElement;
    expect(textarea.value).toContain("move:");
    expect(textarea.value).toContain("park_position");
    // The panel is a supplement to the structured form, not a replacement —
    // both are visible at once.
    expect(screen.getByText("Named Positions")).toBeInTheDocument();
    expect(screen.getByText(/Step 1:/)).toBeInTheDocument();
  });

  it("applies edits from the raw textarea into steps/positions on Apply to form", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({ steps: STEPS, positions: null });

    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));
    const textarea = screen.getByLabelText("Raw YAML");
    const nextYaml = [
      "positions:",
      "  park_position:",
      "    - 360",
      "    - 250",
      "    - 85",
      "protocol:",
      "  - home: null",
      "",
    ].join("\n");
    // A raw YAML blob (with literal braces/brackets) is entered as one
    // paste rather than keystroke-by-keystroke — user.type() treats `{`
    // and `[` as special key-sequence syntax, which a real YAML document
    // will always contain.
    fireEvent.change(textarea, { target: { value: nextYaml } });
    await user.click(screen.getByRole("button", { name: "Apply to form" }));

    expect(props.onLocalChange).toHaveBeenCalledWith([{ command: "home", args: {} }]);
    expect(props.onPositionsChange).toHaveBeenCalledWith({ park_position: [360, 250, 85] });

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(props.onSave).toHaveBeenCalledWith(
      "move.yaml",
      expect.objectContaining({
        positions: { park_position: [360, 250, 85] },
        protocol: [{ command: "home", args: {} }],
      }),
    );
  });

  it("shows a parse error and does not apply when the YAML doesn't parse", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({ steps: STEPS });

    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));
    const textarea = screen.getByLabelText("Raw YAML");
    fireEvent.change(textarea, { target: { value: "protocol: [unterminated" } });
    await user.click(screen.getByRole("button", { name: "Apply to form" }));

    expect(screen.getByText(/must be sufficiently indented/i)).toBeInTheDocument();
    expect(props.onLocalChange).not.toHaveBeenCalled();
  });

  it("rejects YAML missing a protocol list without applying", async () => {
    const user = userEvent.setup();
    const props = renderProtocol({ steps: STEPS });

    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));
    const textarea = screen.getByLabelText("Raw YAML");
    fireEvent.change(textarea, { target: { value: "positions: {}\n" } });
    await user.click(screen.getByRole("button", { name: "Apply to form" }));

    expect(screen.getByText(/`protocol:` must be a list/i)).toBeInTheDocument();
    expect(props.onLocalChange).not.toHaveBeenCalled();
  });

  it("hides the textarea again on Hide raw YAML", async () => {
    const user = userEvent.setup();
    renderProtocol({ steps: STEPS });

    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));
    await user.click(screen.getByRole("button", { name: "Hide raw YAML" }));

    expect(screen.queryByLabelText("Raw YAML")).not.toBeInTheDocument();
  });
});

function baseProps(): React.ComponentProps<typeof ProtocolEditor> {
  return {
    configs: ["move.yaml"],
    selectedFile: "move.yaml",
    onSelectFile: vi.fn(),
    onImportFile: vi.fn(),
    commands: COMMANDS,
    deck: DECK,
    gantry: GANTRY,
    steps: STEPS,
    positions: null,
    baseline: null,
    onSave: vi.fn(),
    onLocalChange: vi.fn(),
    onPositionsChange: vi.fn(),
    onValidate: vi.fn(),
    validationErrors: null,
    isValidating: false,
    onRefresh: vi.fn(),
    onRun: vi.fn(),
    onCancelRun: vi.fn(),
    unsavedConfigs: [],
    canRun: true,
    isRunning: false,
    isCancelingRun: false,
    runResult: null,
    runError: null,
  };
}

const MULTI_DISPENSE: CommandInfo = {
  name: "multi_dispense", description: "Aspirate once, dispense portions",
  args: [
    { name: "source", type: "str", required: true, default: null },
    { name: "destinations", type: "list[str]", required: true, default: null },
    { name: "volumes", type: "list[float]", required: true, default: null },
    { name: "speed", type: "float", required: false, default: 50 },
  ],
};
const MULTI_ARGS = { source: "plate_1.A1", destinations: ["plate_1.B1", "plate_1.B2"], volumes: [20, 30], speed: 50 };
function renderMulti(args: Record<string, unknown> = MULTI_ARGS, overrides: Partial<React.ComponentProps<typeof ProtocolEditor>> = {}) {
  return renderProtocol({ commands: [...COMMANDS, MULTI_DISPENSE], steps: [{ command: "multi_dispense", args }], ...overrides });
}

describe("multi-dispense destination rows", () => {
  it("repeats paired destinations across wells and keeps incomplete rows blocked", async () => {
    const user = userEvent.setup();
    const args = { ...MULTI_ARGS, source: "stock", destinations: ["plate_1.A1", "plate_1.B2"] };
    const props = renderMulti(args, {
      deck: { ...DECK, labware: [{ ...DECK.labware[0], wells: {
        A1: { x: 0, y: 0, z: 0 }, A2: { x: 9, y: 0, z: 0 },
      } }] },
    });

    await user.click(screen.getByRole("button", { name: /Add repeat/ }));
    await user.click(screen.getByRole("button", { name: "Create repeat" }));

    expect(screen.getByLabelText("Step 1 child 1 destination 1")).toHaveValue("plate_1.A1");
    expect(screen.getByLabelText("Step 1 child 1 destination 2")).toHaveValue("plate_1.B2");
    expect(screen.getByLabelText("Step 1 child 1 volume 1 (µL)")).toHaveValue("20");
    expect(screen.getByLabelText("Step 1 child 1 volume 2 (µL)")).toHaveValue("30");
    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(props.onValidate).toHaveBeenLastCalledWith({ protocol: [
      { command: "repeat", args: { labware: "plate_1", template_well: "A1", wells: ["A1", "A2"], steps: [
        { command: "multi_dispense", args },
      ] } },
    ] });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();

    await user.clear(screen.getByLabelText("Step 1 child 1 destination 2"));

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled();
  });

  it("loads saved arrays and submits paired numeric arrays to Save and Validate", async () => {
    const user = userEvent.setup();
    const props = renderMulti();
    expect(screen.getByRole("table", { name: "Step 1 dispense destinations" })).toBeInTheDocument();
    expect(screen.getByLabelText("Step 1 destination 2")).toHaveValue("plate_1.B2");
    const volume = screen.getByLabelText("Step 1 volume 1 (µL)");
    await user.clear(volume);
    await user.type(volume, "20.05");
    expect(volume).toHaveValue("20.05");
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    const body = { protocol: [{ command: "multi_dispense", args: { ...MULTI_ARGS, volumes: [20.05, 30] } }] };
    expect(props.onValidate).toHaveBeenLastCalledWith(body);
    expect(props.onSave).toHaveBeenLastCalledWith("move.yaml", body);
  });

  it("adds and removes paired rows repeatedly, including removing all rows", async () => {
    const user = userEvent.setup();
    const props = renderMulti();
    await user.click(screen.getByRole("button", { name: "Remove destination 1 from step 1" }));
    expect(screen.getByLabelText("Step 1 destination 1")).toHaveValue("plate_1.B2");
    expect(screen.getByLabelText("Step 1 volume 1 (µL)")).toHaveValue("30");
    for (let i = 0; i < 2; i++) {
      await user.click(screen.getByRole("button", { name: "Add destination" }));
      expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
      await user.type(screen.getByLabelText("Step 1 destination 2"), "plate_1.A2");
      await user.type(screen.getByLabelText("Step 1 volume 2 (µL)"), "12.5");
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
      await user.click(screen.getByRole("button", { name: "Remove destination 1 from step 1" }));
      expect(screen.getByLabelText("Step 1 volume 1 (µL)")).toHaveValue("12.5");
    }
    await user.click(screen.getByRole("button", { name: "Remove destination 1 from step 1" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Add at least one destination and volume.");
    expect(props.onLocalChange).toHaveBeenLastCalledWith([{ command: "multi_dispense", args: { ...MULTI_ARGS, destinations: [], volumes: [] } }]);
  });

  it.each(["", "-1", "0", "Infinity", "1e309", "NaN", "12abc", "1e", "."])("blocks invalid volume %j without retaining the prior number", async (invalid) => {
    const user = userEvent.setup();
    const props = renderMulti();
    fireEvent.change(screen.getByLabelText("Step 1 volume 1 (µL)"), { target: { value: invalid } });
    expect(screen.getByLabelText("Step 1 volume 1 (µL)")).toHaveAttribute("aria-invalid", "true");
    for (const name of ["Save", "Validate", "Run Protocol"]) expect(screen.getByRole("button", { name })).toBeDisabled();
    await user.keyboard("{Control>}s{/Control}");
    expect(props.onSave).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Step 1 volume 1 (µL)"), { target: { value: "2.5e1" } });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(props.onLocalChange).toHaveBeenLastCalledWith([{ command: "multi_dispense", args: { ...MULTI_ARGS, volumes: [25, 30] } }]);
  });

  it("preserves unmatched values and allows completing a mismatched saved list", async () => {
    const user = userEvent.setup();
    const props = renderMulti({ ...MULTI_ARGS, destinations: ["plate_1.B1"], volumes: [20, 30] });
    expect(screen.getByLabelText("Step 1 volume 2 (µL)")).toHaveValue("30");
    expect(screen.getByRole("alert")).toHaveTextContent("matching volume");
    await user.type(screen.getByLabelText("Step 1 destination 2"), "plate_1.B2");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(props.onSave).toHaveBeenLastCalledWith("move.yaml", { protocol: [{ command: "multi_dispense", args: MULTI_ARGS }] });
  });

  it("keeps malformed list values visible in raw YAML until explicitly repaired", async () => {
    const user = userEvent.setup();
    const props = renderMulti({ ...MULTI_ARGS, destinations: "plate_1.B1,plate_1.B2" });
    expect(screen.getByRole("alert")).toHaveTextContent("must be lists");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));
    expect((screen.getByLabelText("Raw YAML") as HTMLTextAreaElement).value).toContain("plate_1.B1,plate_1.B2");
    expect(props.onLocalChange).not.toHaveBeenCalled();
  });

  it("round trips table edits through raw YAML and reapplies new rows to the table", async () => {
    const user = userEvent.setup();
    const props = renderMulti();
    fireEvent.change(screen.getByLabelText("Step 1 volume 2 (µL)"), { target: { value: "40.5" } });
    await user.click(screen.getByRole("button", { name: "Edit raw YAML" }));
    const yaml = screen.getByLabelText("Raw YAML") as HTMLTextAreaElement;
    expect(yaml.value).toContain("40.5");
    await user.click(screen.getByRole("button", { name: "Apply to form" }));
    expect(screen.getByLabelText("Step 1 volume 2 (µL)")).toHaveValue("40.5");
    fireEvent.change(yaml, { target: { value: "protocol:\n  - multi_dispense:\n      source: plate_1.A1\n      destinations: [plate_1.B2]\n      volumes: [12.5]\n" } });
    await user.click(screen.getByRole("button", { name: "Apply to form" }));
    expect(screen.queryByLabelText("Step 1 volume 2 (µL)")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Step 1 volume 1 (µL)")).toHaveValue("12.5");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(props.onSave).toHaveBeenLastCalledWith("move.yaml", { protocol: [{ command: "multi_dispense", args: { source: "plate_1.A1", destinations: ["plate_1.B2"], volumes: [12.5] } }] });
  });

  it("starts a newly added command with empty editable lists", async () => {
    const user = userEvent.setup();
    renderMulti(MULTI_ARGS, { steps: [] });
    await user.selectOptions(screen.getByRole("combobox", { name: "Add step" }), "multi_dispense");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Add at least one destination");
    await user.click(screen.getByRole("button", { name: "Add destination" }));
    expect(screen.getByLabelText("Step 1 destination 1")).toHaveValue("");
  });

  it("edits and renames repeated destinations without changing another child", async () => {
    const user = userEvent.setup();
    const args = { ...MULTI_ARGS, source: "park", destinations: ["park", "plate_1.B2"] };
    const repeat = { command: "repeat", args: { labware: "plate_1", template_well: "A1", wells: ["A1", "A2"], steps: [
      { command: "multi_dispense", args },
      { command: "multi_dispense", args: MULTI_ARGS },
    ] } };
    const props = renderMulti(args, { steps: [repeat], positions: { park: [1, 2, 3] } });
    const first = screen.getByLabelText("Step 1 child 1 destination 1");
    const second = screen.getByLabelText("Step 1 child 2 destination 1");
    expect(first.getAttribute("list")).not.toBe(second.getAttribute("list"));
    await user.type(screen.getByLabelText("Position 1 name"), "2");
    expect(first).toHaveValue("park2");
    expect(second).toHaveValue("plate_1.B1");
    const volume = screen.getByLabelText("Step 1 child 1 volume 1 (µL)");
    await user.clear(volume);
    await user.type(volume, "25");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(props.onSave).toHaveBeenLastCalledWith("move.yaml", {
      positions: { park2: [1, 2, 3] },
      protocol: [{ ...repeat, args: { ...repeat.args, steps: [
        { command: "multi_dispense", args: { ...args, source: "park2", destinations: ["park2", "plate_1.B2"], volumes: [25, 30] } },
        { command: "multi_dispense", args: MULTI_ARGS },
      ] } }],
    });
  });

  it("renames named destinations without changing volumes or unrelated positions", async () => {
    const user = userEvent.setup();
    const props = renderMulti({ ...MULTI_ARGS, destinations: ["park", "plate_1.B2"] }, { positions: { park: [1, 2, 3] } });
    await user.type(screen.getByLabelText("Position 1 name"), "2");
    expect(props.onLocalChange).toHaveBeenLastCalledWith([{ command: "multi_dispense", args: { ...MULTI_ARGS, destinations: ["park2", "plate_1.B2"] } }]);
  });
});

describe("multi-dispense incomplete saved rows", () => {
  it.each([
    { ...MULTI_ARGS, destinations: ["", "plate_1.B2"] },
    { ...MULTI_ARGS, destinations: ["   ", "plate_1.B2"] },
    { ...MULTI_ARGS, volumes: [20] },
    { ...MULTI_ARGS, volumes: [20, null] },
    { ...MULTI_ARGS, volumes: [20, true] },
    { ...MULTI_ARGS, volumes: [20, "30"] },
  ])("blocks incomplete or nonnumeric rows without silently dropping them: %j", (args) => {
    const props = renderMulti(args);
    expect(screen.getByLabelText("Step 1 destination 2")).toHaveValue("plate_1.B2");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run Protocol" })).toBeDisabled();
    expect(props.onLocalChange).not.toHaveBeenCalled();
  });
});
