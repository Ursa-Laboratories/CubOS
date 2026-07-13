import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ProtocolEditor from "./ProtocolEditor";
import type { CommandInfo, DeckResponse, GantryResponse, ProtocolResponse, ProtocolStep } from "../../types";

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
        a1: null,
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
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderProtocol({ unsavedConfigs: ["Protocol"], baseline, onRefresh });

    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(onRefresh).toHaveBeenCalled();
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(1);

    confirmSpy.mockRestore();
  });

  it("keeps edits when the user cancels the discard confirm", async () => {
    const user = userEvent.setup();
    const baseline: ProtocolResponse = { filename: "move.yaml", steps: STEPS, positions: null };
    const onRefresh = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderProtocol({ unsavedConfigs: ["Protocol"], baseline, onRefresh });

    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.getAllByText(/^Step \d:$/)).toHaveLength(2);

    confirmSpy.mockRestore();
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
