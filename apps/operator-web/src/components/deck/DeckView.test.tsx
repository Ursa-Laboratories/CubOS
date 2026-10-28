import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DeckResponse } from "../../types";
import DeckView from "./DeckView";

const scene = vi.hoisted(() => ({
  create: vi.fn(),
  renderer: { update: vi.fn(), select: vi.fn(), labels: vi.fn(), frame: vi.fn(), view: vi.fn(), zoom: vi.fn(), rotate: vi.fn(), dispose: vi.fn() },
}));
vi.mock("./three/sceneRenderer", () => ({
  createSceneRenderer: (...args: unknown[]) => {
    scene.create(...args);
    const host = args[0] as HTMLElement;
    if (!host.querySelector("canvas")) {
      const canvas = document.createElement("canvas");
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", "3D deck canvas");
      canvas.tabIndex = 0;
      host.appendChild(canvas);
    }
    return scene.renderer;
  },
}));

const deck: DeckResponse = { filename: "demo.yaml", labware: [{
  key: "plate", config: { type: "well_plate", name: "Demo plate", model_name: "p", rows: 1, columns: 2, length: 100, width: 60, height: 12, calibration: { a1: null, a2: { x: 9, y: 0, z: 0 } }, x_offset: 9, y_offset: 9 },
  wells: { A1: { x: 10, y: 20, z: 14 }, A2: { x: 19, y: 20, z: 14 } }, positions: { A1: { x: 10, y: 20, z: 14 }, A2: { x: 19, y: 20, z: 14 } },
}] };
const props = { deck, instruments: null, gantryPosition: null, machineXRange: [0, 300] as [number, number], machineYRange: [0, 200] as [number, number], machineZRange: [0, 120] as [number, number], yAxisMotion: "head" as const };

beforeEach(() => {
  scene.create.mockClear();
  Object.values(scene.renderer).forEach(method => method.mockClear());
  scene.create.mockImplementation(() => scene.renderer);
});

describe("DeckView", () => {
  it("starts in 2D and allocates the 3D scene only after an explicit switch", async () => {
    render(<DeckView {...props} />);
    expect(screen.getByRole("button", { name: "2D" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("deck-visualization")).toBeInTheDocument();
    expect(scene.create).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "3D" }));
    await waitFor(() => expect(scene.create).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId("deck-3d")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "3D" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "2D" }));
    expect(screen.getByTestId("deck-visualization")).toBeInTheDocument();
    expect(scene.renderer.dispose).toHaveBeenCalledTimes(1);
  });

  it("routes camera and display controls to the renderer without deck actions", async () => {
    render(<DeckView {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "3D" }));
    await waitFor(() => expect(scene.create).toHaveBeenCalled());
    const updatesBeforeControls = scene.renderer.update.mock.calls.length;
    const selectionsBeforeControls = scene.renderer.select.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: /Orbit/ }));
    fireEvent.click(screen.getByRole("button", { name: /Top/ }));
    fireEvent.click(screen.getByRole("button", { name: /Fit/ }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    fireEvent.click(screen.getByLabelText("Labels"));
    fireEvent.click(screen.getByLabelText("Frame"));

    expect(scene.renderer.view.mock.calls).toEqual([["orbit"], ["top"], ["fit"]]);
    expect(scene.renderer.zoom.mock.calls).toEqual([[1 / 1.2], [1.2]]);
    expect(scene.renderer.labels).toHaveBeenLastCalledWith(false);
    expect(scene.renderer.frame).toHaveBeenLastCalledWith(true);
    expect(scene.renderer.rotate).not.toHaveBeenCalled();
    expect(scene.renderer.update).toHaveBeenCalledTimes(updatesBeforeControls);
    expect(scene.renderer.select).toHaveBeenCalledTimes(selectionsBeforeControls);
  });

  it("keeps gantry hotkeys from seeing keys pressed on the canvas or nested controls", async () => {
    const windowKey = vi.fn();
    const windowKeyUp = vi.fn();
    window.addEventListener("keydown", windowKey);
    window.addEventListener("keyup", windowKeyUp);
    try {
      render(<DeckView {...props} />);
      fireEvent.click(screen.getByRole("button", { name: "3D" }));
      const canvas = await screen.findByRole("img", { name: "3D deck canvas" });
      fireEvent.keyDown(canvas, { key: "ArrowLeft" });
      fireEvent.keyUp(canvas, { key: "ArrowLeft" });
      fireEvent.keyDown(screen.getByRole("button", { name: "Zoom in" }), { key: "ArrowUp" });
      fireEvent.keyUp(screen.getByRole("button", { name: "Zoom in" }), { key: "ArrowUp" });
      expect(windowKey).not.toHaveBeenCalled();
      expect(windowKeyUp.mock.calls.map(([event]) => event.key)).toEqual(["ArrowLeft", "ArrowUp"]);
      expect(scene.renderer.rotate).toHaveBeenCalledWith(0.15, 0);
    } finally {
      window.removeEventListener("keydown", windowKey);
      window.removeEventListener("keyup", windowKeyUp);
    }
  });

  it("contains keyboard activation keys from the outer 2D/3D toggle", () => {
    const windowKey = vi.fn();
    window.addEventListener("keydown", windowKey);
    try {
      render(<DeckView {...props} />);
      fireEvent.keyDown(screen.getByRole("button", { name: "3D" }), { key: "ArrowUp" });
      expect(windowKey).not.toHaveBeenCalled();
      expect(scene.create).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", windowKey);
    }
  });

  it("offers an actionable 2D fallback if the 3D renderer cannot initialize", async () => {
    scene.create.mockImplementationOnce(() => { throw new Error("no WebGL"); });
    render(<DeckView {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "3D" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/3D graphics are unavailable.*Switch to 2D/i);
    fireEvent.click(screen.getByRole("button", { name: "2D" }));
    expect(screen.getByTestId("deck-visualization")).toBeInTheDocument();
  });
});
