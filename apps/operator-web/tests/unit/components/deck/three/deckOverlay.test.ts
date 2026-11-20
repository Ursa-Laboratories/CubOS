import { Box3, Group, InstancedMesh, Matrix4, Mesh, Vector3 } from "three";
import { describe, expect, it, vi } from "vitest";
import { createDeckOverlay, disposeDeckOverlay } from "../../../../../src/components/deck/three/deckOverlay";
import type { DeckResponse } from "../../../../../src/types";

const point = (x: number, y: number, z: number) => ({ x, y, z });

describe("configured deck overlay", () => {
  it("draws the holder from its base and rotates the nested plate using resolved wells", () => {
    const a1 = point(100, 40, 17), a2 = point(100, 49, 17);
    const deck: DeckResponse = {
      filename: "deck.yaml",
      labware: [{
        key: "holder", location: point(93, 44, 3), wells: null,
        geometry: { length: 75, width: 100, height: 8 },
        positions: { plate: a1, "plate.A1": a1, "plate.A2": a2, "plate.B1": point(109, 40, 17) },
        config: {
          type: "well_plate_holder", name: "Holder",
          well_plate: {
            model_name: "plate", rows: 2, columns: 2, length: 90, width: 45, height: 10, well_depth: 6,
            calibration: { a1: point(4, 5, 0), a2: point(13, 5, 0) }, x_offset: 9, y_offset: 9,
          },
        },
      }],
    };
    const overlay = createDeckOverlay(deck);
    overlay.updateMatrixWorld(true);
    const holder = overlay.getObjectByName("holder")!;
    const plate = overlay.getObjectByName("holder.plate")!;
    const socket = plate.getObjectByName("sockets") as InstancedMesh;
    expect(plate.rotation.z).toBeCloseTo(Math.PI / 2);
    expect(new Box3().setFromObject(holder).min.y).toBeCloseTo(3);
    const plateBounds = new Box3().setFromObject(plate);
    expect(plateBounds.getSize(new Vector3()).toArray().map(Math.round)).toEqual([45, 10, 90]);
    expect(plateBounds.max.y).toBeCloseTo(17);
    expect(socket.count).toBe(3);
    const matrix = new Matrix4();
    socket.getMatrixAt(0, matrix);
    const location = socket.localToWorld(new Vector3().setFromMatrixPosition(matrix));
    expect(location.x).toBeCloseTo(100);
    expect(location.y).toBeCloseTo(14);
    expect(location.z).toBeCloseTo(-40);
  });

  it("uses resolved vial rims and includes only tips that are present", () => {
    const deck: DeckResponse = {
      filename: "deck.yaml",
      labware: [{
        key: "vials", location: point(40, 80, 0), wells: null,
        positions: { sample: point(45, 90, 24) },
        config: {
          type: "vial_holder", name: "Holder", vials: {
            sample: { model_name: "vial", height: 20, diameter: 10, location: { x: 0, y: 0 }, capacity_ul: 100, working_volume_ul: 100 },
          },
        },
      }, {
        key: "rack", wells: null,
        positions: { A1: point(10, 20, 32), A2: point(19, 20, 32), park: point(100, 20, 32) },
        config: { type: "tip_rack", name: "Rack", model_name: "rack", length: 45, width: 25, height: 20, tip_present: { A1: false, A2: true } },
      }],
    };
    const overlay = createDeckOverlay(deck);
    const vial = overlay.getObjectByName("vials.sample")!;
    expect(vial.getWorldPosition(new Vector3()).toArray().map(Math.round)).toEqual([45, 14, -90]);
    expect(new Box3().setFromObject(vial).max.y).toBeCloseTo(24);
    const tips = overlay.getObjectByName("loaded-tips") as InstancedMesh;
    expect(tips.count).toBe(1);
    const matrix = new Matrix4();
    tips.getMatrixAt(0, matrix);
    expect(tips.localToWorld(new Vector3().setFromMatrixPosition(matrix)).x).toBeCloseTo(19);
  });

  it("disposes each overlay resource once and detaches the group", () => {
    const overlay = createDeckOverlay({ filename: "deck.yaml", labware: [{
      key: "bin", wells: null, location: point(10, 10, 15), config: { type: "tip_disposal", name: "Bin" },
    }] });
    const parent = new Group();
    parent.add(overlay);
    const mesh = overlay.getObjectByProperty("isMesh", true) as Mesh;
    const geometry = vi.spyOn(mesh.geometry, "dispose");
    const material = vi.spyOn(Array.isArray(mesh.material) ? mesh.material[0] : mesh.material, "dispose");

    disposeDeckOverlay(overlay);

    expect(geometry).toHaveBeenCalledOnce();
    expect(material).toHaveBeenCalledOnce();
    expect(parent.children).toEqual([]);
  });
});
