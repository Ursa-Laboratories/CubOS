import type { Coordinate3D, DeckResponse, LabwareResponse } from "../../../types";

export interface ScenePoint {
  label: string;
  position: Coordinate3D;
  present?: boolean;
}

export interface SceneObject {
  id: string;
  kind: string;
  body: { center: Coordinate3D; size: Coordinate3D; rotationZ: number };
  points: ScenePoint[];
  wellDepth?: number;
}

type Dimensions = { length?: unknown; width?: unknown; height?: unknown };

const PLATE = { x: 127, y: 85, z: 14 };
const FIXTURE = { x: 50, y: 50, z: 20 };
const resolvedPoint = (value: unknown): value is Coordinate3D => {
  if (!value || typeof value !== "object") return false;
  const point = value as Partial<Coordinate3D>;
  return [point.x, point.y, point.z].every(Number.isFinite);
};
const dimension = (v: unknown, fallback: number) =>
  typeof v === "number" && Number.isFinite(v) && v > 0 ? v : fallback;
const sizeFor = (dimensions: Dimensions, fallback: Coordinate3D): Coordinate3D => ({
  x: dimension(dimensions.length, fallback.x),
  y: dimension(dimensions.width, fallback.y),
  z: dimension(dimensions.height, fallback.z),
});

function resolvedPoints(positions: LabwareResponse["positions"] | null): ScenePoint[] {
  return Object.entries(positions ?? {}).flatMap(([label, position]) =>
    resolvedPoint(position) && label !== "location" ? [{ label, position }] : [],
  );
}

function centerOfGrid(points: ScenePoint[], anchor: Coordinate3D): Coordinate3D {
  if (!points.length) return anchor;
  const xs = points.map(p => p.position.x), ys = points.map(p => p.position.y);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2, z: anchor.z };
}

function gridAngle(points: ScenePoint[]): number {
  const a1 = points.find(p => p.label === "A1")?.position;
  if (!a1) return 0;
  const a2 = points.find(p => p.label === "A2")?.position;
  const b1 = points.find(p => p.label === "B1")?.position;
  if (a2) return Math.atan2(a2.y - a1.y, a2.x - a1.x);
  if (b1) return Math.atan2(b1.y - a1.y, b1.x - a1.x) + Math.PI / 2;
  return 0;
}

function gridObject(
  id: string, kind: "well_plate" | "tip_rack", points: ScenePoint[],
  anchor: Coordinate3D | undefined, dimensions: Dimensions, wellDepth?: unknown,
): SceneObject | undefined {
  const reference = points.find(p => p.label === "A1")?.position ?? anchor ?? points[0]?.position;
  if (!reference) return;
  const rotationZ = gridAngle(points);
  const center = { ...centerOfGrid(points, reference) };
  const size = sizeFor(dimensions, PLATE);
  if (kind === "tip_rack" && points.length) {
    const spread = points.reduce(({ x, y }, { position }) => {
      const dx = position.x - center.x, dy = position.y - center.y;
      return {
        x: Math.max(x, 2 * Math.abs(dx * Math.cos(rotationZ) + dy * Math.sin(rotationZ))),
        y: Math.max(y, 2 * Math.abs(dy * Math.cos(rotationZ) - dx * Math.sin(rotationZ))),
      };
    }, { x: 0, y: 0 });
    if ((size.x < spread.x || size.y < spread.y) && size.y >= spread.x && size.x >= spread.y) {
      [size.x, size.y] = [size.y, size.x];
    }
    size.x = Math.max(size.x, spread.x + 9);
    size.y = Math.max(size.y, spread.y + 9);
  }
  center.z = reference.z - size.z / 2;
  return { id, kind, body: { center, size, rotationZ }, points, wellDepth: dimension(wellDepth, 25) };
}

function vial(id: string, position: Coordinate3D, diameter: unknown, height: unknown): SceneObject {
  const d = dimension(diameter, 10), h = dimension(height, 30);
  const center = { ...position, z: position.z - h / 2 };
  return {
    id, kind: "vial",
    body: { center, size: { x: d, y: d, z: h }, rotationZ: 0 },
    points: [{ label: id.split(".").at(-1) ?? id, position }],
  };
}

function fixture(item: LabwareResponse, anchor: Coordinate3D, points: ScenePoint[]): SceneObject {
  const { key, config, geometry } = item;
  const size = sizeFor({
    length: geometry?.length ?? ("length" in config ? config.length : undefined),
    width: geometry?.width ?? ("width" in config ? config.width : undefined),
    height: geometry?.height ?? ("height" in config ? config.height : undefined),
  }, FIXTURE);
  const center = { ...centerOfGrid(points, anchor) };
  center.z = anchor.z + (config.type === "tip_disposal" ? -size.z / 2 : size.z / 2);
  return { id: key, kind: config.type, body: { center, size, rotationZ: 0 }, points: [] };
}

export function buildOverlayModel(deck: DeckResponse): SceneObject[] {
  const objects: SceneObject[] = [];
  for (const item of deck.labware) {
    const { key, config, geometry } = item;
    const positions = resolvedPoints(item.positions);
    const configured = "location" in config ? config.location : undefined;
    const anchor = resolvedPoint(item.location) ? item.location
      : resolvedPoint(configured) ? configured : undefined;

    switch (config.type) {
      case "well_plate": {
        const object = gridObject(key, config.type, resolvedPoints(item.wells ?? item.positions), anchor,
          { length: geometry?.length ?? config.length, width: geometry?.width ?? config.width, height: geometry?.height ?? config.height },
          config.well_depth);
        if (object) objects.push(object);
        break;
      }
      case "tip_rack": {
        const tips = positions.filter(p => /^[A-Z]+[1-9]\d*$/.test(p.label)).map(p => ({
          ...p, present: config.tip_present?.[p.label],
        }));
        const object = gridObject(key, config.type, tips, anchor,
          { length: config.length ?? geometry?.length, width: config.width ?? geometry?.width, height: config.height ?? geometry?.height },
          12);
        if (object) objects.push(object);
        break;
      }
      case "well_plate_holder": {
        const prefix = "plate.";
        const wells = positions.filter(p => p.label.startsWith(prefix)).map(p => ({ ...p, label: p.label.slice(prefix.length) }));
        if (anchor) objects.push(fixture(item, anchor, wells));
        if (config.well_plate) {
          const reference = positions.find(p => p.label === "plate")?.position;
          const plate = gridObject(`${key}.plate`, "well_plate", wells, reference, config.well_plate, config.well_plate.well_depth);
          if (plate) objects.push(plate);
        }
        break;
      }
      case "vial_holder": {
        const children = positions.filter(p => Object.hasOwn(config.vials ?? {}, p.label));
        if (anchor) objects.push(fixture(item, anchor, children));
        for (const { label, position } of children) {
          const vialConfig = config.vials![label];
          objects.push(vial(`${key}.${label}`, position, vialConfig.diameter, vialConfig.height));
        }
        break;
      }
      case "vial_grid":
        for (const { label, position } of positions) {
          objects.push(vial(`${key}.${label}`, position, config.vial_diameter, config.vial_height));
        }
        break;
      case "vial":
        if (anchor) objects.push(vial(key, anchor, config.diameter, config.height));
        break;
      case "tip_disposal":
        if (anchor) objects.push(fixture(item, anchor, []));
        break;
    }
  }
  return objects;
}
