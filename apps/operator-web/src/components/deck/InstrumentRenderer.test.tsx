import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import InstrumentRenderer from "./InstrumentRenderer";
import { machineToSvg } from "../../utils/coordinates";
import type { GantryPosition, InstrumentConfig } from "../../types";

const position: GantryPosition = { connected: true, calibration_active: false, x: 90, y: 155, z: 50, work_x: 90, work_y: 155, work_z: 50, status: "Idle" };
const instrument: InstrumentConfig = { type: "pipette", vendor: "opentrons", offset_x: 10, offset_y: -5,
  pipette_model: "p300_multi_gen2", channel_geometry: { axis: "x", length_mm: 80, width_mm: 30, height_mm: 120 } };
const props = { label: "pipette", instrument, gantryPosition: position, svgWidth: 600, svgHeight: 420,
  machineXRange: [0, 600] as [number, number], machineYRange: [0, 300] as [number, number] };

describe("eight-channel instrument visualization", () => {
  it.each(["x", "y"] as const)("draws the measured head and anchors the %s row at its first tip", axis => {
    render(<svg><InstrumentRenderer {...props} instrument={{ ...instrument, channel_geometry: { ...instrument.channel_geometry!, axis } }} /></svg>);
    const tips = screen.getAllByTestId("pipette-channel");
    expect(tips).toHaveLength(8);
    const first = machineToSvg(100, 150, 600, 420, [0, 600], [0, 300]);
    const last = machineToSvg(axis === "x" ? 163 : 100, axis === "y" ? 213 : 150, 600, 420, [0, 600], [0, 300]);
    expect(Number(tips[0].getAttribute("cx"))).toBeCloseTo(first.sx);
    expect(Number(tips[0].getAttribute("cy"))).toBeCloseTo(first.sy);
    expect(Number(tips[7].getAttribute("cx"))).toBeCloseTo(last.sx);
    expect(Number(tips[7].getAttribute("cy"))).toBeCloseTo(last.sy);
    const scale = machineToSvg(1, 0, 600, 420, [0, 600], [0, 300]).sx - machineToSvg(0, 0, 600, 420, [0, 600], [0, 300]).sx;
    expect(Number(screen.getByTestId("pipette-head").getAttribute("width"))).toBeCloseTo((axis === "x" ? 80 : 30) * scale);
    expect(Number(screen.getByTestId("pipette-head").getAttribute("height"))).toBeCloseTo((axis === "x" ? 30 : 80) * scale);
    expect(screen.getByText(/80 × 30 × 120 mm/)).toBeInTheDocument();
    expect(screen.getByText(`${axis === "x" ? "leftmost" : "frontmost"} reference tip (WPos + offset)`)).toBeInTheDocument();
  });

  it("keeps negative home-frame coordinates and shows the full head offline", () => {
    render(<svg><InstrumentRenderer {...props} gantryPosition={null} instrument={{ ...instrument, offset_x: -100, offset_y: -150 }}
      machineXRange={[-600, 0]} machineYRange={[-300, 0]} /></svg>);
    const first = machineToSvg(-100, -150, 600, 420, [-600, 0], [-300, 0]);
    expect(Number(screen.getAllByTestId("pipette-channel")[0].getAttribute("cx"))).toBeCloseTo(first.sx);
    expect(screen.getByTestId("pipette-head")).toHaveAttribute("stroke-dasharray", "4 2");
  });

  it("preserves the existing single-channel marker", () => {
    render(<svg><InstrumentRenderer {...props} instrument={{ type: "pipette", vendor: "opentrons", offset_x: 0, offset_y: 0 }} /></svg>);
    expect(screen.queryByTestId("pipette-head")).not.toBeInTheDocument();
    expect(screen.getByText("pipette (pipette) at (90.0, 155.0)")).toBeInTheDocument();
  });
});
