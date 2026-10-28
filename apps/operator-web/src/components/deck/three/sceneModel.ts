import type { Coordinate3D, DeckResponse, GantryPosition, InstrumentConfig, LabwareResponse } from "../../../types";

export type SceneShape = "box" | "cylinder";
export interface SceneBounds { x: [number, number]; y: [number, number]; z: [number, number] }
export interface ScenePoint { id: string; label: string; position: Coordinate3D; present?: boolean; parentId?: string }
/** `size` always uses deck-space X, Y, Z dimensions, including cylinders. */
export interface SceneBody { shape: SceneShape; center: Coordinate3D; size: Coordinate3D; rotationZ: number; schematic: true }
export interface SceneObject { id: string; parentId?: string; parentLabel?: string; kind: string; modelName?: string; hasChildren?: boolean; label: string; body: SceneBody; points: ScenePoint[]; info: string }
export interface SceneInstrument {
  id: string; label: string; type: string; configuredOffset: { x: number; y: number; depth: number };
  position: Coordinate3D | null; positionUnavailable: boolean; body: SceneBody | null; info: string;
}
export interface SceneModel { bounds: SceneBounds; configuredBounds: SceneBounds; objects: SceneObject[]; points: ScenePoint[]; instruments: SceneInstrument[]; yAxisMotion: "head" | "bed" }
export interface BuildSceneModelInput {
  deck: DeckResponse | null; instruments: Record<string, InstrumentConfig> | null; gantryPosition: GantryPosition | null;
  machineXRange: [number, number]; machineYRange: [number, number]; machineZRange: [number, number]; yAxisMotion: "head" | "bed";
}

const DEFAULT = { plate: { x: 127, y: 85, z: 14 }, fixture: { x: 50, y: 50, z: 20 }, vial: { d: 10, h: 30 }, instrument: { x: 24, y: 18, z: 40 }, pipetteHeight: 85 };
const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const dim = (n: unknown, fallback: number) => finite(n) && n > 0 ? n : fallback;
const isPoint = (v: unknown): v is Coordinate3D => !!v && typeof v === "object" && finite((v as Coordinate3D).x) && finite((v as Coordinate3D).y) && finite((v as Coordinate3D).z);
const coord = (x: number, y: number, z: number): Coordinate3D => ({ x, y, z });
const box = (center: Coordinate3D, size: Coordinate3D, rotationZ = 0): SceneBody => ({ shape: "box", center, size, rotationZ, schematic: true });
const cylinder = (center: Coordinate3D, diameter: number, height: number): SceneBody => ({ shape: "cylinder", center, size: coord(diameter, diameter, height), rotationZ: 0, schematic: true });
const objectId = (key: string, ...path: string[]) => JSON.stringify(["labware", key, ...path]);
const instrumentId = (key: string) => JSON.stringify(["instrument", key]);
const humanize = (value: string) => value.replaceAll("_", " ");

function validPositions(positions: Record<string, Coordinate3D> | null | undefined) {
  return Object.entries(positions ?? {}).filter((entry): entry is [string, Coordinate3D] => isPoint(entry[1]));
}
function pointMarkers(item: LabwareResponse): ScenePoint[] {
  const config = item.config;
  if (config.type === "well_plate") return validPositions(item.wells).map(([id, p]) => ({ id: `${item.key}.${id}`, label: id, position: p, parentId: item.key }));
  if (config.type === "tip_rack") return validPositions(item.positions).filter(([id]) => id !== "location" && !id.includes(".")).map(([id, p]) => ({ id: `${item.key}.${id}`, label: id, position: p, present: config.tip_present?.[id], parentId: item.key }));
  if (config.type === "well_plate_holder") return [];
  if (config.type === "vial_holder") return [];
  if (config.type === "vial_grid") return validPositions(item.positions).filter(([id]) => id !== "location").map(([id, p]) => ({ id: `${item.key}.${id}`, label: id, position: p, parentId: item.key }));
  return [];
}
function angleFor(points: ScenePoint[], prefix = ""): number {
  const byLabel = new Map(points.map(p => [p.label, p.position]));
  const a1 = byLabel.get(`${prefix}A1`);
  if (!a1) return 0;
  // Columns define the physical X axis. For a one-column plate, the row axis
  // supplies the long axis; the canonical row direction determines its sign.
  const a2 = byLabel.get(`${prefix}A2`);
  const b1 = byLabel.get(`${prefix}B1`);
  const adjacent = a2 ?? b1;
  if (adjacent) {
    const rowOnly = !a2 && !!b1;
    const direction = Math.atan2(adjacent.y - a1.y, adjacent.x - a1.x);
    return direction + (rowOnly ? Math.PI / 2 : 0);
  }
  const fallback = points.find(p => p.position.x !== a1.x || p.position.y !== a1.y);
  return fallback ? Math.atan2(fallback.position.y - a1.y, fallback.position.x - a1.x) : 0;
}
function extents(points: ScenePoint[], anchor: Coordinate3D | null) {
  const ps = points.map(p => p.position);
  if (ps.length === 0 && anchor) ps.push(anchor);
  if (ps.length === 0) return null;
  return { minX: Math.min(...ps.map(p => p.x)), maxX: Math.max(...ps.map(p => p.x)), minY: Math.min(...ps.map(p => p.y)), maxY: Math.max(...ps.map(p => p.y)) };
}
function bodyFor(item: LabwareResponse, points: ScenePoint[]): SceneBody | null {
  const c = item.config;
  const configLocation = "location" in c && isPoint(c.location) ? c.location : null;
  const anchor = isPoint(item.location) ? item.location : configLocation ?? points[0]?.position ?? null;
  if (c.type === "vial" && isPoint(c.location)) {
    const h = dim(c.height, DEFAULT.vial.h), d = dim(c.diameter, DEFAULT.vial.d);
    // Vial.location.z is the rim; the body extends toward -Z by outer height.
    return cylinder(coord(c.location.x, c.location.y, c.location.z - h / 2), d, h);
  }
  const e = extents(points, anchor);
  if (!e) return null;
  const center = coord((e.minX + e.maxX) / 2, (e.minY + e.maxY) / 2, anchor!.z);
  if (c.type === "vial_grid") return null; // Each vial is a child object, never a central cylinder.
  const plate = c.type === "well_plate";
  const fallback = plate ? DEFAULT.plate : DEFAULT.fixture;
  const geom = item.geometry;
  const sx = dim(plate ? c.length : geom?.length ?? ("length" in c ? c.length : null), fallback.x);
  const sy = dim(plate ? c.width : geom?.width ?? ("width" in c ? c.width : null), fallback.y);
  const sz = dim(plate ? c.height : geom?.height ?? ("height" in c ? c.height : null), fallback.z);
  const rotation = plate ? angleFor(points) : 0;
  // HolderLabware.location is an absolute reference point, not generally a
  // declared center or bottom. Only a supplied seat-from-bottom datum lets
  // the schematic envelope treat it as the physical base plane.
  const holderBaseKnown = "labware_seat_height_from_bottom" in c && finite(c.labware_seat_height_from_bottom);
  const surfaceAnchored = plate || c.type === "tip_rack" || c.type === "tip_disposal";
  const bodyCenterZ = surfaceAnchored ? center.z - sz / 2 : holderBaseKnown ? anchor!.z + sz / 2 : anchor!.z;
  return box(coord(center.x, center.y, bodyCenterZ), coord(sx, sy, sz), rotation);
}
function holderEnvelopePoints(item: LabwareResponse): ScenePoint[] {
  if (!item.positions) return [];
  const config = item.config;
  const entries = validPositions(item.positions).filter(([id]) => id !== "location" && id !== "plate");
  if (config.type === "well_plate_holder") return entries.filter(([id]) => id.startsWith("plate.")).map(([id, p]) => ({ id: `${item.key}.${id}`, label: id.slice(6), position: p }));
  if (config.type === "vial_holder") return entries.filter(([id]) => Object.prototype.hasOwnProperty.call(config.vials ?? {}, id)).map(([id, p]) => ({ id: `${item.key}.${id}`, label: id, position: p }));
  return [];
}
function makeChildVial(id: string, pointId: string, label: string, p: Coordinate3D, diameter: unknown, height: unknown, parentId?: string, parentLabel?: string, modelName?: string): SceneObject {
  const d = dim(diameter, DEFAULT.vial.d), h = dim(height, DEFAULT.vial.h);
  const displayLabel = parentLabel ? `${parentLabel} · ${label}` : label;
  const pt: ScenePoint = { id: pointId, label, position: p, ...(parentId ? { parentId } : {}) };
  return { id, ...(parentId ? { parentId } : {}), ...(parentLabel ? { parentLabel } : {}), kind: "vial", modelName, label: displayLabel, body: cylinder(coord(p.x, p.y, p.z - h / 2), d, h), points: [pt], info: `${displayLabel} · vial · schematic body` };
}
function objectBounds(body: SceneBody) {
  const c = Math.abs(Math.cos(body.rotationZ)), s = Math.abs(Math.sin(body.rotationZ));
  const hx = c * body.size.x / 2 + s * body.size.y / 2;
  const hy = s * body.size.x / 2 + c * body.size.y / 2;
  return { x: [body.center.x - hx, body.center.x + hx], y: [body.center.y - hy, body.center.y + hy], z: [body.center.z - body.size.z / 2, body.center.z + body.size.z / 2] };
}

export function buildSceneModel(input: BuildSceneModelInput): SceneModel {
  const objects: SceneObject[] = [];
  const points: ScenePoint[] = [];
  for (const item of input.deck?.labware ?? []) {
    const pts = pointMarkers(item);
    const bodyPoints = item.config.type === "well_plate_holder" || item.config.type === "vial_holder" ? holderEnvelopePoints(item) : pts;
    const body = bodyFor(item, bodyPoints);
    if (body) {
      const label = item.config.name || item.key;
      const renderedPoints = ["well_plate_holder", "vial_holder"].includes(item.config.type) ? [] : pts;
      objects.push({ id: objectId(item.key), kind: item.config.type, modelName: item.config.model_name, hasChildren: item.config.type === "well_plate_holder" && !!item.config.well_plate, label, body, points: renderedPoints, info: `${label} · ${humanize(item.config.type)} · schematic body` });
      points.push(...renderedPoints);
    }
    if (item.config.type === "well_plate_holder" && item.config.well_plate) {
      const nested = item.config.well_plate;
      const resolved = validPositions(item.positions).filter(([id]) => id.startsWith("plate.") && id !== "plate");
      const childPoints = resolved.map(([id, p]) => ({ id: `${item.key}.${id}`, label: id.slice(6), position: p, parentId: item.key }));
      const a1 = item.positions?.["plate.A1"];
      if (a1 && isPoint(a1)) {
        const h = dim(nested.height, DEFAULT.plate.z);
        const e = extents(childPoints, a1)!;
        const angle = angleFor(childPoints);
        const center = coord((e.minX + e.maxX) / 2, (e.minY + e.maxY) / 2, a1.z - h / 2);
        const childBody = box(center, coord(dim(nested.length, DEFAULT.plate.x), dim(nested.width, DEFAULT.plate.y), h), angle);
        objects.push({ id: objectId(item.key, "plate"), parentId: objectId(item.key), kind: "well_plate", modelName: nested.model_name, label: nested.name ?? "Well plate", body: childBody, points: childPoints, info: `${nested.name ?? "Well plate"} · nested well plate · schematic body` });
        points.push(...childPoints);
      }
    }
    if (item.config.type === "vial_holder") {
      for (const [vialId, config] of Object.entries(item.config.vials ?? {})) {
        const p = item.positions?.[vialId];
        if (isPoint(p)) {
          const child = makeChildVial(objectId(item.key, vialId), `${item.key}.${vialId}`, vialId, p, config.diameter, config.height, objectId(item.key), item.config.name || item.key, config.model_name);
          objects.push(child); points.push(...child.points);
        }
      }
    }
    if (item.config.type === "vial_grid") {
      for (const [vialId, p] of validPositions(item.positions).filter(([id]) => id !== "location")) {
        const d = item.config.vial_diameter, h = item.config.vial_height;
        const child = makeChildVial(objectId(item.key, vialId), `${item.key}.${vialId}`, vialId, p, d, h, objectId(item.key), item.config.name || item.key, item.config.vial_model_name);
        objects.push(child); points.push(...child.points);
      }
    }
  }
  const gantry = input.gantryPosition;
  const live = !!gantry?.connected && finite(gantry.work_x) && finite(gantry.work_y) && finite(gantry.work_z);
  const instruments = Object.entries(input.instruments ?? {}).map(([id, inst]): SceneInstrument => {
    const ox = finite(inst.offset_x) ? inst.offset_x : 0, oy = finite(inst.offset_y) ? inst.offset_y : 0, depth = finite(inst.depth) ? inst.depth : 0;
    const position = live ? coord(gantry!.work_x! + ox, gantry!.work_y! + oy, gantry!.work_z! - depth) : null;
    const validPosition = position && isPoint(position) ? position : null;
    const instrumentHeight = /pipette/i.test(inst.type) ? DEFAULT.pipetteHeight : DEFAULT.instrument.z;
    const body = validPosition ? box(coord(validPosition.x, validPosition.y, validPosition.z + instrumentHeight / 2), coord(DEFAULT.instrument.x, DEFAULT.instrument.y, instrumentHeight)) : null;
    const displayName = humanize(id);
    return { id: instrumentId(id), label: validPosition ? displayName : `${displayName} — Position unavailable`, type: inst.type, configuredOffset: { x: ox, y: oy, depth }, position: validPosition, positionUnavailable: !validPosition, body, info: validPosition ? `${displayName} · ${humanize(inst.type)} · schematic live instrument` : `${displayName} · ${humanize(inst.type)} · Position unavailable` };
  });
  const uniquePoints = [...new Map(points.map(p => [p.id, p])).values()];
  const coordBounds = (axis: "x" | "y" | "z", range: [number, number]): [number, number] => {
    const vals: number[] = [...uniquePoints.map(p => p.position[axis]), ...instruments.flatMap(i => i.position ? [i.position[axis]] : [])];
    for (const object of objects) {
      const b = objectBounds(object.body)[axis];
      vals.push(b[0], b[1]);
    }
    for (const instrument of instruments) {
      if (!instrument.body) continue;
      const b = objectBounds(instrument.body)[axis];
      vals.push(b[0], b[1]);
    }
    return [Math.min(range[0], ...vals), Math.max(range[1], ...vals)];
  };
  return {
    bounds: { x: coordBounds("x", input.machineXRange), y: coordBounds("y", input.machineYRange), z: coordBounds("z", input.machineZRange) },
    configuredBounds: { x: [...input.machineXRange], y: [...input.machineYRange], z: [...input.machineZRange] },
    objects, points: uniquePoints, instruments, yAxisMotion: input.yAxisMotion,
  };
}
