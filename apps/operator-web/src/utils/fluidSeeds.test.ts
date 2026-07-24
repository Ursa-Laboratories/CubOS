import { describe, expect, it } from "vitest";
import {
  buildSeedFluids,
  createCompositionRow,
  createSeedRow,
  validateSeedRows,
  volumeContainerKeys,
} from "./fluidSeeds";
import type { DeckResponse, FluidSeedRow } from "../types";

function seedRow(overrides: Partial<FluidSeedRow> = {}): FluidSeedRow {
  return { ...createSeedRow(), ...overrides };
}

function compRow(component: string, volume: string) {
  return { ...createCompositionRow(), component, volume };
}

describe("buildSeedFluids", () => {
  it("returns {} for no rows (preserves the empty-state default)", () => {
    expect(buildSeedFluids([])).toEqual({});
  });

  it("skips blank (containerless) rows", () => {
    const rows = [seedRow({ container: "", volume: "500" })];
    expect(buildSeedFluids(rows)).toEqual({});
  });

  it("omits composition when no component rows are filled in", () => {
    const rows = [seedRow({ container: "s1", volume: "6500" })];
    expect(buildSeedFluids(rows)).toEqual({ s1: { volume_ul: 6500 } });
  });

  it("includes a composition map when component rows are present", () => {
    const rows = [
      seedRow({
        container: "w2",
        volume: "19800",
        composition: [compRow("acn", "6300"), compRow("dmf", "13500")],
      }),
    ];
    expect(buildSeedFluids(rows)).toEqual({
      w2: { volume_ul: 19800, composition: { acn: 6300, dmf: 13500 } },
    });
  });

  it("trims container and component names", () => {
    const rows = [
      seedRow({ container: "  s1  ", volume: "100", composition: [compRow(" water ", "100")] }),
    ];
    expect(buildSeedFluids(rows)).toEqual({ s1: { volume_ul: 100, composition: { water: 100 } } });
  });
});

describe("validateSeedRows", () => {
  it("accepts a bare volume with no composition", () => {
    expect(validateSeedRows([seedRow({ container: "s1", volume: "6500" })])).toEqual([]);
  });

  it("accepts a zero volume", () => {
    expect(validateSeedRows([seedRow({ container: "s4", volume: "0" })])).toEqual([]);
  });

  it("ignores fully blank rows", () => {
    expect(validateSeedRows([seedRow(), seedRow()])).toEqual([]);
  });

  it("flags a missing volume", () => {
    const errors = validateSeedRows([seedRow({ container: "s1", volume: "" })]);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/needs a volume/i);
  });

  it("flags a negative volume", () => {
    const errors = validateSeedRows([seedRow({ container: "s1", volume: "-5" })]);
    expect(errors[0]).toMatch(/zero or greater/i);
  });

  it("flags a composition that does not sum to the volume", () => {
    const errors = validateSeedRows([
      seedRow({ container: "w2", volume: "19800", composition: [compRow("acn", "6300")] }),
    ]);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/composition sums to 6300/i);
  });

  it("accepts a composition that sums exactly", () => {
    expect(
      validateSeedRows([
        seedRow({
          container: "w2",
          volume: "19800",
          composition: [compRow("acn", "6300"), compRow("dmf", "13500")],
        }),
      ]),
    ).toEqual([]);
  });

  it("flags a composition amount with no component name", () => {
    const errors = validateSeedRows([
      seedRow({ container: "s1", volume: "100", composition: [compRow("", "100")] }),
    ]);
    expect(errors.some((e) => /no component name/i.test(e))).toBe(true);
  });

  it("flags duplicate container keys", () => {
    const errors = validateSeedRows([
      seedRow({ container: "s1", volume: "100" }),
      seedRow({ container: "s1", volume: "200" }),
    ]);
    expect(errors.some((e) => /more than one row/i.test(e))).toBe(true);
  });

  it("tolerates float noise in the composition sum", () => {
    const errors = validateSeedRows([
      seedRow({
        container: "s1",
        volume: "0.3",
        composition: [compRow("a", "0.1"), compRow("b", "0.2")],
      }),
    ]);
    expect(errors).toEqual([]);
  });
});

describe("volumeContainerKeys", () => {
  const deck: DeckResponse = {
    filename: "deck.yaml",
    labware: [
      {
        key: "plate_1",
        config: { type: "well_plate" } as never,
        wells: { A1: { x: 0, y: 0, z: 0 }, A2: { x: 1, y: 0, z: 0 } },
      },
      {
        key: "s1",
        config: { type: "vial" } as never,
        wells: null,
      },
      {
        key: "rack",
        config: { type: "vial_grid" } as never,
        wells: null,
        positions: { A1: { x: 0, y: 0, z: 0 }, B1: { x: 0, y: 1, z: 0 } },
      },
      {
        key: "tips",
        config: { type: "tip_rack" } as never,
        wells: null,
        positions: { A1: { x: 0, y: 0, z: 0 } },
      },
    ],
  };

  it("enumerates wells, bare vials, and grid positions but excludes tip racks", () => {
    expect(volumeContainerKeys(deck)).toEqual([
      "plate_1.A1",
      "plate_1.A2",
      "rack.A1",
      "rack.B1",
      "s1",
    ]);
  });

  it("returns [] for a missing deck", () => {
    expect(volumeContainerKeys(null)).toEqual([]);
  });
});
