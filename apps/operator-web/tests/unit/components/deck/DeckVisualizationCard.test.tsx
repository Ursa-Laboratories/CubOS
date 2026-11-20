import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import DeckVisualizationCard from "../../../../src/components/deck/DeckVisualizationCard";
import type { DeckViewMode } from "../../../../src/components/deck/DeckVisualizationCard";
import type { GantryPosition } from "../../../../src/types";

const { renderScene } = vi.hoisted(() => ({
  renderScene: vi.fn(),
}));

vi.mock("../../../../src/components/deck/PolarDeckScene", () => ({
  default: renderScene,
}));

const reportedPosition: GantryPosition = {
  x: 90,
  y: 80,
  z: 70,
  work_x: 0,
  work_y: 12,
  work_z: 13,
  status: "Idle",
  connected: true,
  calibration_active: false,
};

function Harness({
  position = reportedPosition,
  positionQuerySucceeded = true,
}: {
  position?: GantryPosition;
  positionQuerySucceeded?: boolean;
}) {
  const [mode, setMode] = useState<DeckViewMode>("2D");
  return (
    <DeckVisualizationCard
      deck={null}
      instruments={null}
      gantryPosition={position}
      mode={mode}
      onModeChange={setMode}
      positionQuerySucceeded={positionQuerySucceeded}
      machineXRange={[0, 390]}
      machineYRange={[0, 390]}
      machineZRange={[-70, 0]}
      yAxisMotion="head"
      gantryType="genmitsu_4040_pro_max"
    />
  );
}

describe("deck visualization mode", () => {
  it("keeps the 2D map by default and opens and closes the 3D scene from the card", async () => {
    renderScene.mockReset().mockImplementation(({ onShow2D }) => (
      <button type="button" onClick={onShow2D}>Return to 2D</button>
    ));
    const user = userEvent.setup();
    render(<Harness />);

    expect(screen.getByRole("button", { name: "2D" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("deck-visualization")).toBeInTheDocument();
    expect(renderScene).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "3D" }));
    const back = await screen.findByRole("button", { name: "Return to 2D" });
    expect(screen.getByRole("button", { name: "3D" })).toHaveAttribute("aria-pressed", "true");
    expect(renderScene.mock.lastCall?.[0]).toMatchObject({
      gantryPosition: { x: 0, y: 12, z: 13 },
      machineZRange: [-70, 0],
      gantryType: "genmitsu_4040_pro_max",
    });

    await user.click(back);
    expect(screen.getByTestId("deck-visualization")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2D" })).toHaveAttribute("aria-pressed", "true");
  });

  it("does not substitute machine coordinates or stale pose for a missing live position", async () => {
    renderScene.mockReset().mockReturnValue(<div>3D scene</div>);
    const user = userEvent.setup();
    const { rerender } = render(<Harness position={{ ...reportedPosition, connected: false }} />);

    await user.click(screen.getByRole("button", { name: "3D" }));
    await screen.findByText("3D scene");
    expect(renderScene.mock.lastCall?.[0].gantryPosition).toBeNull();

    rerender(<Harness position={{ ...reportedPosition, work_y: null }} />);
    expect(renderScene.mock.lastCall?.[0].gantryPosition).toBeNull();
    rerender(<Harness position={{ ...reportedPosition, work_y: Number.NaN }} />);
    expect(renderScene.mock.lastCall?.[0].gantryPosition).toBeNull();
    rerender(<Harness positionQuerySucceeded={false} />);
    expect(renderScene.mock.lastCall?.[0].gantryPosition).toBeNull();
  });

  it("shows the 2D map when 3D rendering fails", async () => {
    renderScene.mockReset().mockImplementation(() => {
      throw new Error("Could not load the scene");
    });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(<Harness />);
      await userEvent.click(screen.getByRole("button", { name: "3D" }));
      expect(await screen.findByText("3D unavailable. Showing the 2D view.")).toHaveAttribute("role", "status");
      expect(screen.getByTestId("deck-visualization")).toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
  });

  it("keeps 3D keyboard input away from gantry jogging and still releases held keys", async () => {
    renderScene.mockReset().mockReturnValue(<button type="button">3D viewport</button>);
    const user = userEvent.setup();
    const keyDown = vi.fn();
    const keyUp = vi.fn();
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    try {
      render(<Harness />);
      const to3D = screen.getByRole("button", { name: "3D" });
      fireEvent.keyDown(to3D, { key: "ArrowLeft" });
      expect(keyDown).toHaveBeenCalledOnce();
      keyDown.mockClear();

      await user.click(to3D);
      const viewport = await screen.findByRole("button", { name: "3D viewport" });
      fireEvent.keyDown(to3D, { key: "ArrowLeft" });
      fireEvent.keyDown(viewport, { key: "Z" });
      expect(keyDown).not.toHaveBeenCalled();
      fireEvent.keyUp(viewport, { key: "Z" });
      expect(keyUp).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
    }
  });
});
