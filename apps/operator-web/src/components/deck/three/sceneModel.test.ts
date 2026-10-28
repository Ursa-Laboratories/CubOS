import { describe, expect, it } from "vitest";
import type { DeckResponse, GantryPosition } from "../../../types";
import { buildSceneModel } from "./sceneModel";

const base = {
  instruments: null,
  gantryPosition: null,
  machineXRange: [-100, 300] as [number, number],
  machineYRange: [-80, 200] as [number, number],
  machineZRange: [-20, 100] as [number, number],
  yAxisMotion: "head" as const,
};
const labwareId = (...path: string[]) => JSON.stringify(["labware", ...path]);

describe("buildSceneModel", () => {
  it("uses API-resolved well coordinates and keeps negative deck bounds", () => {
    const deck: DeckResponse = { filename: "test.yaml", labware: [{
      key: "plate", config: { type: "well_plate", name: "Plate", model_name: "p", rows: 1, columns: 2, length: 100, width: 60, height: 12, calibration: { a1: null, a2: { x: 1, y: 0, z: 0 } }, x_offset: 9, y_offset: 9 },
      wells: { A1: { x: -40, y: 5, z: 20 }, A2: { x: -31, y: 5, z: 20 } }, positions: { A1: { x: -40, y: 5, z: 20 }, A2: { x: -31, y: 5, z: 20 } },
    }] };
    const model = buildSceneModel({ ...base, deck });
    expect(model.objects[0].body.size).toEqual({ x: 100, y: 60, z: 12 });
    expect(model.points.map(p => p.position.x)).toEqual([-40, -31]);
    expect(model.bounds.x[0]).toBeLessThan(0);
    expect(model.configuredBounds).toEqual({ x: [-100, 300], y: [-80, 200], z: [-20, 100] });
  });

  it("uses named A1 to A2 even when API well keys arrive shuffled", () => {
    const deck: DeckResponse = { filename: "r.yaml", labware: [{
      key: "p", config: { type: "well_plate", name: "P", model_name: "p", rows: 2, columns: 2, length: 100, width: 60, height: 10, calibration: { a1: null, a2: { x: 0, y: 1, z: 0 } }, x_offset: 9, y_offset: 9 },
      wells: { B2: { x: 9, y: 9, z: 15 }, A2: { x: 0, y: 9, z: 15 }, B1: { x: 9, y: 0, z: 15 }, A1: { x: 0, y: 0, z: 15 } }, positions: {},
    }] };
    expect(buildSceneModel({ ...base, deck }).objects[0].body.rotationZ).toBeCloseTo(Math.PI / 2);
  });

  it("uses A1 to B1 to recover the plate X axis for a one-column plate", () => {
    const deck: DeckResponse = { filename: "one.yaml", labware: [{
      key: "p", config: { type: "well_plate", name: "P", model_name: "p", rows: 2, columns: 1, length: 30, width: 90, height: 8, calibration: { a1: null, a2: { x: 0, y: 1, z: 0 } }, x_offset: 9, y_offset: 9 },
      wells: { A1: { x: 5, y: 5, z: 10 }, B1: { x: 5, y: -5, z: 10 } }, positions: {},
    }] };
    expect(buildSceneModel({ ...base, deck }).objects[0].body.rotationZ).toBeCloseTo(0);
  });

  it("rotates footprint extents when fitting camera bounds", () => {
    const deck: DeckResponse = { filename: "wide.yaml", labware: [{
      key: "p", config: { type: "well_plate", name: "P", model_name: "p", rows: 1, columns: 2, length: 100, width: 20, height: 10, calibration: { a1: null, a2: { x: 0, y: 1, z: 0 } }, x_offset: 9, y_offset: 9 },
      wells: { A1: { x: 0, y: 0, z: 15 }, A2: { x: 0, y: 9, z: 15 } }, positions: {},
    }] };
    const model = buildSceneModel({ ...base, deck, machineXRange: [0, 0], machineYRange: [0, 0] });
    expect(model.bounds.x[1] - model.bounds.x[0]).toBeCloseTo(20);
    expect(model.bounds.y[1] - model.bounds.y[0]).toBeCloseTo(100);
  });

  it("represents nested holder contents once as child objects and unique leaf points", () => {
    const deck: DeckResponse = { filename: "nested.yaml", labware: [{
      key: "holder", config: { type: "well_plate_holder", name: "Holder", location: { x: 10, y: 20, z: 0 }, labware_seat_height_from_bottom: 3, well_plate: { name: "Plate", model_name: "p", rows: 1, columns: 2, calibration: { a1: null, a2: { x: 9, y: 0, z: 0 } }, x_offset: 9, y_offset: 9, length: 100, width: 60, height: 10 } },
      wells: null, location: { x: 10, y: 20, z: 0 }, geometry: { length: 120, width: 90, height: 18 }, positions: { location: { x: 10, y: 20, z: 0 }, plate: { x: 15, y: 25, z: 18 }, "plate.A1": { x: 15, y: 25, z: 18 }, "plate.A2": { x: 24, y: 25, z: 18 } },
    }] };
    const model = buildSceneModel({ ...base, deck });
    expect(model.objects.map(o => o.id)).toEqual([labwareId("holder"), labwareId("holder", "plate")]);
    expect(model.objects[1].parentId).toBe(labwareId("holder"));
    expect(model.objects[0].body.center).toEqual({ x: 19.5, y: 25, z: 9 });
    expect(model.objects[0].points).toEqual([]);
    expect(model.objects[1].points.map(p => p.id)).toEqual(["holder.plate.A1", "holder.plate.A2"]);
    expect(new Set(model.points.map(p => p.id)).size).toBe(model.points.length);
  });

  it("creates each vial-grid vial at its resolved position, with XYZ diameter-height-diameter ordering", () => {
    const deck: DeckResponse = { filename: "vials.yaml", labware: [{
      key: "grid", config: { type: "vial_grid", name: "Grid", model_name: "g", rows: 1, columns: 2, calibration: { a1: null, a2: { x: 18, y: 0, z: 0 } }, x_offset: 18, y_offset: 18, vial_height: 40, vial_diameter: 12, capacity_ul: 500, working_volume_ul: 400 },
      wells: null, positions: { A1: { x: 1, y: 2, z: 50 }, A2: { x: 19, y: 2, z: 50 } },
    }] };
    const model = buildSceneModel({ ...base, deck });
    expect(model.objects.map(o => o.id)).toEqual([labwareId("grid", "A1"), labwareId("grid", "A2")]);
    expect(model.objects[0].body.size).toEqual({ x: 12, y: 12, z: 40 });
    expect(model.objects[0].body.center.z).toBe(30); // resolved Z is vial rim; body extends down.
    expect(model.points).toHaveLength(2);
  });

  it("does not fabricate an instrument position without complete connected WPos", () => {
    const instruments = { pipette: { type: "pipette", vendor: "x", offset_x: 4, offset_y: -3, depth: 20 } };
    for (const gantryPosition of [null, { connected: false, work_x: 1, work_y: 2, work_z: 3 }, { connected: true, work_x: 1, work_y: null, work_z: 3 }] as const) {
      const model = buildSceneModel({ ...base, deck: null, instruments, gantryPosition: gantryPosition as GantryPosition | null });
      expect(model.instruments[0]).toMatchObject({ position: null, body: null, positionUnavailable: true });
    }
  });

  it("uses mount offsets and depth for a schematic pipette at a live contact datum", () => {
    const live: GantryPosition = { connected: true, status: "Idle", x: 0, y: 0, z: 0, work_x: 10, work_y: 50, work_z: 30, calibration_active: false };
    const model = buildSceneModel({ ...base, deck: null, instruments: { pipette: { type: "pipette", vendor: "x", offset_x: 2, offset_y: -5, depth: 8 } }, gantryPosition: live, yAxisMotion: "bed" });
    expect(model.instruments[0].position).toEqual({ x: 12, y: 45, z: 22 });
    expect(model.instruments[0].body?.size.z).toBe(85);
    expect(model.instruments[0].body?.center.z).toBe(64.5);
    expect(model.yAxisMotion).toBe("bed");
  });

  it("filters malformed positions and offsets from render data and camera bounds", () => {
    const deck: DeckResponse = { filename: "bad.yaml", labware: [{
      key: "p", config: { type: "well_plate", name: "P", model_name: "p", rows: 1, columns: 1, length: 50, width: 20, height: 8, calibration: { a1: null, a2: { x: 1, y: 0, z: 0 } }, x_offset: 9, y_offset: 9 },
      wells: { A1: { x: 1, y: Number.NaN, z: 3 } }, positions: {},
    }] };
    const gantryPosition: GantryPosition = { connected: true, status: "Idle", x: 0, y: 0, z: 0, work_x: 1, work_y: 2, work_z: 3, calibration_active: false };
    const model = buildSceneModel({ ...base, deck, instruments: { pipette: { type: "pipette", vendor: "x", offset_x: Number.NaN, offset_y: 1, depth: 0 } }, gantryPosition });
    expect(model.points).toEqual([]);
    expect(model.instruments[0].position?.x).toBe(1);
    expect(Object.values(model.bounds).flat().every(Number.isFinite)).toBe(true);
  });

  it("namespaces instrument, top-level labware, and nested selection identities", () => {
    const deck: DeckResponse = { filename: "collisions.yaml", labware: [
      {
        key: "holder", config: { type: "well_plate_holder", name: "Holder", location: { x: 0, y: 0, z: 0 }, well_plate: { name: "Nested", model_name: "p", rows: 1, columns: 2, calibration: { a1: null, a2: { x: 9, y: 0, z: 0 } }, x_offset: 9, y_offset: 9, length: 100, width: 60, height: 10 } },
        wells: null, location: { x: 0, y: 0, z: 0 }, geometry: { length: 120, width: 90, height: 18 }, positions: { location: { x: 0, y: 0, z: 0 }, "plate.A1": { x: 5, y: 5, z: 18 }, "plate.A2": { x: 14, y: 5, z: 18 } },
      },
      {
        key: "holder.plate", config: { type: "well_plate", name: "Top level", model_name: "p", rows: 1, columns: 1, length: 50, width: 30, height: 10, calibration: { a1: null, a2: { x: 9, y: 0, z: 0 } }, x_offset: 9, y_offset: 9 },
        wells: { A1: { x: 150, y: 20, z: 10 } }, positions: { A1: { x: 150, y: 20, z: 10 } },
      },
      { key: "pipette", config: { type: "tip_disposal", name: "Disposal", location: { x: 220, y: 20, z: 12 }, length: 40, width: 30, height: 20 }, wells: null, location: { x: 220, y: 20, z: 12 }, geometry: { length: 40, width: 30, height: 20 }, positions: { discard: { x: 220, y: 20, z: 12 } } },
    ] };
    const model = buildSceneModel({ ...base, deck, instruments: { pipette: { type: "pipette", vendor: "test", offset_x: 0, offset_y: 0 } } });
    const ids = [...model.objects.map(o => o.id), ...model.instruments.map(i => i.id)];
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain(labwareId("holder", "plate"));
    expect(ids).toContain(labwareId("holder.plate"));
    expect(model.instruments[0].id).toBe(JSON.stringify(["instrument", "pipette"]));
    expect(model.objects.find(o => o.id === labwareId("holder", "plate"))?.parentId).toBe(labwareId("holder"));
    expect(model.objects.find(o => o.id === labwareId("holder", "plate"))?.label).toBe("Nested");
  });
});
