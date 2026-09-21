import type { Coordinate3D } from "../../types";

export type DeckView = "top" | "isometric" | "front-xz" | "side-yz";
export type ProjectionAxis = "x" | "y";

export interface ProjectedPoint {
  horizontal: number;
  vertical: number;
}

/** Project deck-frame coordinates without changing their signs. Vertical is up. */
export function projectDeckCoordinate(point: Coordinate3D, view: DeckView): ProjectedPoint {
  if (view === "front-xz") return { horizontal: point.x, vertical: point.z };
  if (view === "side-yz") return { horizontal: point.y, vertical: point.z };
  if (view === "isometric") {
    return {
      horizontal: point.x - point.y * 0.5,
      vertical: point.z + (point.x + point.y) * 0.25,
    };
  }
  return { horizontal: point.x, vertical: point.y };
}

export function projectionAxes(view: DeckView): { horizontal: ProjectionAxis; vertical: "y" | "z" } {
  if (view === "side-yz") return { horizontal: "y", vertical: "z" };
  if (view === "front-xz") return { horizontal: "x", vertical: "z" };
  return { horizontal: "x", vertical: "y" };
}

export function normalizeDeckView(value: string | undefined): DeckView {
  if (value === "isometric" || value === "front-xz" || value === "side-yz") return value;
  return "top";
}

export function signedRange(range: [number, number]): [number, number] {
  return range[0] <= range[1] ? range : [range[1], range[0]];
}
