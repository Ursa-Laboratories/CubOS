import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DeckResponse, GantryPosition } from "../../../types";
import type { DeckViewProps } from "../DeckView";
import DeckScene from "./DeckScene";
const labwareId = (...path: string[]) => JSON.stringify(["labware", ...path]);
const instrumentId = (...path: string[]) => JSON.stringify(["instrument", ...path]);

const scene = vi.hoisted(() => ({
  create: vi.fn(), onSelect: undefined as ((id: string) => void) | undefined,
  onFailure: undefined as ((message: string) => void) | undefined,
  renderer: { update: vi.fn(), select: vi.fn(), labels: vi.fn(), frame: vi.fn(), view: vi.fn(), zoom: vi.fn(), rotate: vi.fn(), dispose: vi.fn() },
}));
vi.mock("./sceneRenderer", () => ({
  createSceneRenderer: (...args: unknown[]) => {
    scene.create(...args);
    scene.onSelect = args[3] as (id: string) => void;
    scene.onFailure = args[4] as (message: string) => void;
    return scene.renderer;
  },
}));

function makeDeck(key: string, label = key): DeckResponse {
  return { filename: `${key}.yaml`, labware: [{
    key, config: { type: "well_plate", name: label, model_name: "p", rows: 1, columns: 2, length: 100, width: 60, height: 12, calibration: { a1: null, a2: { x: 9, y: 0, z: 0 } }, x_offset: 9, y_offset: 9 },
    wells: { A1: { x: 10, y: 20, z: 14 }, A2: { x: 19, y: 20, z: 14 } }, positions: { A1: { x: 10, y: 20, z: 14 }, A2: { x: 19, y: 20, z: 14 } },
  }] };
}
const base: DeckViewProps = {
  deck: makeDeck("plate", "Plate one"), instruments: null, gantryPosition: null,
  machineXRange: [0, 300], machineYRange: [0, 200], machineZRange: [0, 120], yAxisMotion: "bed",
};
beforeEach(() => {
  scene.create.mockClear(); scene.onSelect = undefined; scene.onFailure = undefined;
  Object.values(scene.renderer).forEach(method => method.mockClear());
  scene.create.mockImplementation(() => scene.renderer);
});

describe("DeckScene", () => {
  it("updates resolved scene data, follows object selection, and disposes resources on unmount", async () => {
    const view = render(<DeckScene {...base} />);
    await waitFor(() => expect(scene.renderer.update).toHaveBeenCalled());
    expect(scene.renderer.update.mock.lastCall?.[0].objects[0]).toMatchObject({ id: labwareId("plate"), label: "Plate one" });
    expect(scene.renderer.select).toHaveBeenLastCalledWith(labwareId("plate"));
    expect(screen.getByText(/Deck coordinates · Moving-bed gantry/)).toBeInTheDocument();

    view.rerender(<DeckScene {...base} deck={makeDeck("plate2", "Plate two")} />);
    await waitFor(() => expect(scene.renderer.update.mock.lastCall?.[0].objects[0].label).toBe("Plate two"));
    expect(scene.renderer.select).toHaveBeenLastCalledWith(labwareId("plate2"));

    view.unmount();
    expect(scene.renderer.dispose).toHaveBeenCalledTimes(1);
  });

  it("prevents focus on an instrument without live position and allows it when WPos arrives", async () => {
    const instruments = { pipette: { type: "pipette", vendor: "test", offset_x: 0, offset_y: 0, depth: 0 } };
    const view = render(<DeckScene {...base} deck={null} instruments={instruments} />);
    const picker = screen.getByRole("combobox", { name: "Selected 3D object" });
    fireEvent.change(picker, { target: { value: instrumentId("pipette") } });
    expect(screen.getByRole("option", { name: /Position unavailable/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Focus selection" })).toBeDisabled();

    const live: GantryPosition = { connected: true, status: "Idle", x: 0, y: 0, z: 0, work_x: 1, work_y: 2, work_z: 3, calibration_active: false };
    view.rerender(<DeckScene {...base} deck={null} instruments={instruments} gantryPosition={live} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Focus selection" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Focus selection" }));
    expect(scene.renderer.view).toHaveBeenLastCalledWith("focus");
  });

  it("contains keydown camera controls while allowing keyup to release a held jog", async () => {
    const windowKey = vi.fn();
    const windowKeyUp = vi.fn();
    window.addEventListener("keydown", windowKey);
    window.addEventListener("keyup", windowKeyUp);
    try {
      const { container } = render(<DeckScene {...base} />);
      await waitFor(() => expect(scene.create).toHaveBeenCalled());
      const host = container.querySelector(".deck3d-canvas")!;
      const canvas = document.createElement("canvas");
      canvas.tabIndex = 0;
      host.appendChild(canvas);
      fireEvent.keyDown(canvas, { key: "ArrowRight" });
      fireEvent.keyUp(canvas, { key: "ArrowRight" });
      fireEvent.keyDown(screen.getByRole("button", { name: "Zoom in" }), { key: "ArrowUp" });
      fireEvent.keyUp(screen.getByRole("button", { name: "Zoom in" }), { key: "ArrowUp" });
      expect(windowKey).not.toHaveBeenCalled();
      expect(windowKeyUp.mock.calls.map(([event]) => event.key)).toEqual(["ArrowRight", "ArrowUp"]);
      expect(scene.renderer.rotate).toHaveBeenCalledWith(-0.15, 0);
      expect(scene.renderer.zoom).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", windowKey);
      window.removeEventListener("keyup", windowKeyUp);
    }
  });

  it("shows a clear recovery message when graphics context fails", async () => {
    render(<DeckScene {...base} />);
    await waitFor(() => expect(scene.create).toHaveBeenCalled());
    scene.onFailure?.("The 3D graphics context was lost. Switch to 2D, or reopen 3D to retry.");
    expect(await screen.findByRole("status")).toHaveTextContent(/graphics context was lost.*Switch to 2D/i);
  });
});
