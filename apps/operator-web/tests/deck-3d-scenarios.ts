import type { DeckResponse, GantryConfig, LabwareResponse, WellPosition } from "../src/types";

export interface PreviewScenario {
  id: string;
  label: string;
  description: string;
  deck: DeckResponse;
  gantry: GantryConfig;
  pose: WellPosition;
}

// Synthetic API-shaped fixtures only. These coordinates are not machine calibration.
function grid(cx: number, cy: number, z: number, rows: number, columns: number, pitch: number, angle = 0): Record<string, WellPosition> {
  return Object.fromEntries(Array.from({ length: rows * columns }, (_, i) => {
    const row = Math.floor(i / columns), col = i % columns;
    const x = (col - (columns - 1) / 2) * pitch, y = ((rows - 1) / 2 - row) * pitch;
    return [String.fromCharCode(65 + row) + (col + 1), { x: cx + x * Math.cos(angle) - y * Math.sin(angle), y: cy + x * Math.sin(angle) + y * Math.cos(angle), z }];
  }));
}

function plate(key: string, name: string, x: number, y: number, count = 96, height = 14.35, angle = 0): LabwareResponse {
  const [rows, columns, pitch] = count === 6 ? [2, 3, 39] : count === 24 ? [4, 6, 18] : count === 384 ? [16, 24, 4.5] : [8, 12, 9];
  const wells = grid(x, y, height, rows, columns, pitch, angle);
  return {
    key, config: { type: "well_plate", name, model_name: "sample_" + count, rows, columns, length: 127.76, width: 85.47, height, x_offset: pitch, y_offset: pitch, calibration: { a1: wells.A1, a2: wells.A2 } },
    wells, positions: wells, geometry: { length: 127.76, width: 85.47, height },
  };
}

function tips(key: string, x: number, y: number, height = 55): LabwareResponse {
  const positions = grid(x, y, height, 8, 12, 9);
  return {
    key, config: { type: "tip_rack", name: key === "tips" ? "Tips" : key.replaceAll("_", " "), model_name: "sample_tips", rows: 8, columns: 12, pickup_z: height, tip_length: 50, x_offset: 9, y_offset: 9, calibration: { a1: positions.A1, a2: positions.A2 }, tip_present: Object.fromEntries(Object.keys(positions).map((id, i) => [id, i >= 8])) },
    wells: null, positions, geometry: { length: 127, width: 85, height },
  };
}

function vial(key: string, name: string, x: number, y: number, height: number, diameter: number): LabwareResponse {
  const location = { x, y, z: height };
  return { key, config: { type: "vial", name, model_name: "sample_vial", height, diameter, location, capacity_ul: 15000, working_volume_ul: 0 }, wells: null, location, geometry: { length: diameter, width: diameter, height } };
}

function vialGrid(key: string, name: string, x: number, y: number, rows = 3, columns = 6, height = 65, diameter = 18): LabwareResponse {
  const positions = grid(x, y, height, rows, columns, diameter + 7);
  return {
    key, config: { type: "vial_grid", name, model_name: "sample_vial_grid", rows, columns, vial_height: height, vial_diameter: diameter, calibration: { a1: positions.A1, a2: positions.A2 }, x_offset: diameter + 7, y_offset: diameter + 7, capacity_ul: 15000, working_volume_ul: 0 },
    wells: null, positions,
  };
}

function vialHolder(key: string, x: number, y: number): LabwareResponse {
  const positions = grid(x, y, 48, 3, 4, 24);
  const location = { x, y, z: 0 };
  return {
    key, config: { type: "vial_holder", name: "12-vial holder", location, labware_seat_height_from_bottom: 13, vials: Object.fromEntries(Object.entries(positions).map(([id, p]) => [id, { model_name: "sample_vial", location: p, height: 35, diameter: 15, capacity_ul: 2000, working_volume_ul: 0 }])) },
    wells: null, location, positions, geometry: { length: 110, width: 85, height: 20 },
  };
}

function raisedPlate(key: string, x: number, y: number): LabwareResponse {
  const surfaceZ = 34.35, location = { x, y, z: 0 };
  const points = grid(x, y, surfaceZ, 8, 12, 9);
  const local = grid(0, 0, 14.35, 8, 12, 9);
  return {
    key, config: { type: "well_plate_holder", name: "Raised plate holder", location, labware_seat_height_from_bottom: 20,
      well_plate: { name: "96-well plate · raised", model_name: "sample_96", rows: 8, columns: 12, length: 127.76, width: 85.47, height: 14.35, x_offset: 9, y_offset: 9, calibration: { a1: local.A1, a2: local.A2 } } },
    wells: null, location, positions: Object.fromEntries(Object.entries(points).map(([id, p]) => ["plate." + id, p])), geometry: { length: 135, width: 95, height: 20 },
  };
}

function cadHolder(x: number, y: number): LabwareResponse {
  const item = raisedPlate("cad_holder", x, y);
  if (item.config.type !== "well_plate_holder") return item;
  item.config.model_name = "tall_wellplate_holder";
  item.config.name = "Cubware plate holder";
  item.config.labware_seat_height_from_bottom = 21;
  // Show the real holder empty until its CAD seat registration is mapped.
  // The source seat is offset/rotated relative to the mesh bounding box.
  item.config.well_plate = null;
  item.positions = {};
  item.geometry = { length: 127.5, width: 176.4, height: 25 };
  return item;
}

function cadTipHolder(x: number, y: number): LabwareResponse {
  const positions = grid(x, y, 66, 2, 15, 8.5);
  return {
    key: "cad_tips", config: { type: "tip_rack", name: "Cubware 30-tip holder", model_name: "cubware_tip_holder_visual", rows: 2, columns: 15, pickup_z: 66, tip_length: 50, x_offset: 8.5, y_offset: 8.5, calibration: { a1: positions.A1, a2: positions.A2 }, tip_present: Object.fromEntries(Object.keys(positions).map(id => [id, false])) },
    wells: null, positions, geometry: { length: 138, width: 21, height: 66 },
  };
}

function waste(x: number, y: number, height = 45): LabwareResponse {
  const location = { x, y, z: height };
  return { key: "waste", config: { type: "tip_disposal", name: "Tip disposal", location }, wells: null, location, geometry: { length: 100, width: 72, height } };
}

function setup(id: string, label: string, description: string, width: number, depth: number, labware: LabwareResponse[], multiInstrument = false): PreviewScenario {
  return {
    id, label, description, deck: { filename: "sample-deck.yaml", labware },
    gantry: {
      serial_port: "OFFLINE-PREVIEW", gantry_type: width <= 300 ? "cub" : "cub_xl",
      cnc: { factory_z_travel_mm: 200, y_axis_motion: width <= 300 ? "bed" : "head" },
      working_volume: { x_min: 0, x_max: width, y_min: 0, y_max: depth, z_min: 0, z_max: 200 },
      instruments: {
        pipette: { type: "pipette", vendor: "sartorius", offset_x: 0, offset_y: 0, depth: 20 },
        ...(multiInstrument ? { optical_probe: { type: "uvvis_ccs", vendor: "thorlabs", offset_x: 65, offset_y: 0, depth: 10 } } : {}),
      },
    },
    pose: { x: width * 0.43, y: depth * 0.54, z: 125 },
  };
}

export const previewScenarios: PreviewScenario[] = [
  setup("cad", "CAD labware · 600 × 400 mm", "Imported Cubware meshes, open wells, hollow vials and studio shading", 600, 400, [
    cadHolder(145, 205), cadTipHolder(430, 245),
    plate("six_well", "6-well plate", 145, 60, 6, 17),
    plate("plate", "96-well plate", 430, 90),
    vialHolder("vials", 145, 345),
    vialGrid("glass_vials", "Glass vials", 430, 345, 2, 5, 70, 20),
  ], true),
  setup("compact", "Compact · 300 × 230 mm", "Original compact setup", 300, 230, [
    plate("plate", "96-well plate", 75, 64), tips("tips", 224, 174), vialHolder("vials", 71, 176), waste(224, 64, 35),
  ]),
  setup("mixed", "Mixed labware · 600 × 400 mm", "6 / 24 / 96 / 384 wells, raised holder, vial grid and tall vials", 600, 400, [
    plate("six_well", "6-well plate", 85, 75, 6, 17),
    plate("twentyfour_well", "24-well plate", 265, 75, 24, 20),
    plate("deep_well", "96 deep-well plate", 445, 75, 96, 45),
    plate("dense_plate", "384-well plate", 85, 215, 384),
    raisedPlate("raised", 265, 215), tips("tips", 445, 215, 65),
    vial("tube_15", "Tall vial · narrow", 65, 340, 90, 18),
    vial("tube_50", "Tall vial · wide", 120, 340, 110, 30),
    vialGrid("vial_grid", "12-vial grid", 290, 340, 2, 6), waste(490, 340),
  ], true),
  setup("large", "Large deck · 900 × 600 mm", "Multiple plate formats, two tip racks, raised plate and two vial grids", 900, 600, [
    plate("six_well", "6-well plate", 100, 90, 6, 17),
    plate("twentyfour_well", "24-well plate", 270, 90, 24, 20),
    plate("plate", "96-well plate", 440, 90),
    plate("dense_plate", "384-well plate", 610, 90, 384),
    plate("deep_well", "96 deep-well plate", 780, 90, 96, 45),
    tips("Tips_A", 100, 250), tips("Tips_B", 270, 250, 75),
    raisedPlate("raised", 440, 250), vialHolder("vials", 610, 250), waste(780, 250),
    vialGrid("vial_grid_a", "40-vial grid", 140, 455, 5, 8, 65, 17),
    vialGrid("vial_grid_b", "24-vial grid · tall", 410, 455, 4, 6, 100, 22),
    plate("rotated", "24-well plate · rotated", 650, 455, 24, 20, Math.PI / 4),
    vial("tube_50", "Tall vial · wide", 815, 440, 110, 30),
  ], true),
  setup("dense", "Dense deck · 1200 × 800 mm", "24 plates and 6 tip racks · over 6,000 displayed positions", 1200, 800, [
    ...Array.from({ length: 24 }, (_, i) => plate("plate_" + (i + 1), (i % 2 ? "96" : "384") + "-well · " + (i + 1), 100 + (i % 6) * 190, 90 + Math.floor(i / 6) * 155, i % 2 ? 96 : 384, i % 3 === 0 ? 40 : 14.35)),
    ...Array.from({ length: 6 }, (_, i) => tips("Tips_" + (i + 1), 100 + i * 190, 710, i % 2 ? 75 : 55)),
  ], true),
];
