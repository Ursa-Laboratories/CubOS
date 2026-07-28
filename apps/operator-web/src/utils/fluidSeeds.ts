// Helpers for the "New fluid state" per-container starting-volume rows.
//
// The versioned API seeds a new fluid state from an `initial_state.fluids`
// map of `<containerKey> -> { volume_ul, composition? }` (see the Python
// `InitialStateSeed`/`FluidSeedItem`). This module owns three concerns for
// that UI:
//   1. enumerating valid container keys from the loaded deck,
//   2. validating operator-entered rows the same way the server would
//      (so a bad row is caught inline rather than as a 4xx), and
//   3. assembling the `fluids` payload from valid rows.
//
// Volumes live in the UI as raw strings so controlled inputs can hold
// partial/empty values; parsing and validation happen here.

import type {
  CompositionSeedRow,
  DeckResponse,
  FluidSeedItem,
  FluidSeedRow,
  LabwareResponse,
} from "../types";

// Mirrors the server's composition-sum tolerance
// (cubos.data.fluid_state._require_composition_sum): abs 1e-6 uL, with a
// tiny relative term so large volumes aren't rejected on float noise.
const VOLUME_TOLERANCE_UL = 1e-6;

// Deck labware whose containers can hold tracked fluid volume, matching the
// server's `_iter_volume_labware` (well plates, vials, vial grids). Tip
// racks, disposals, and walls are excluded — they carry no fluid volume.
const VOLUME_LABWARE_TYPES = new Set(["well_plate", "vial", "vial_grid"]);

let seedRowCounter = 0;

function nextId(prefix: string): string {
  seedRowCounter += 1;
  return `${prefix}-${seedRowCounter}`;
}

export function createSeedRow(): FluidSeedRow {
  return { id: nextId("seed"), container: "", volume: "", composition: [] };
}

export function createCompositionRow(): CompositionSeedRow {
  return { id: nextId("comp"), component: "", volume: "" };
}

function isVolumeLabware(item: LabwareResponse): boolean {
  return VOLUME_LABWARE_TYPES.has(item.config.type);
}

// Container target keys for one labware item, in the same `<key>` /
// `<key>.<location>` form the protocol editor already uses for aspirate /
// dispense targets (and which the server resolves via
// `Deck.resolve_labware_target`). A bare vial yields just its key; wells and
// vial-grid positions yield `<key>.<location>`.
function containerKeysForLabware(item: LabwareResponse): string[] {
  const locations = new Set<string>();
  if (item.wells) {
    for (const well of Object.keys(item.wells)) locations.add(well);
  }
  if (item.positions) {
    for (const position of Object.keys(item.positions)) locations.add(position);
  }
  if (locations.size === 0) return [item.key];
  return Array.from(locations).map((location) => `${item.key}.${location}`);
}

// All volume-bearing container keys on the deck, sorted for a stable
// datalist. Used to suggest valid keys; the form still accepts only the
// rows the operator fills in, so unlisted containers simply default to 0.
export function volumeContainerKeys(deck: DeckResponse | null | undefined): string[] {
  if (!deck) return [];
  const keys = deck.labware
    .filter(isVolumeLabware)
    .flatMap(containerKeysForLabware);
  return Array.from(new Set(keys)).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true }),
  );
}

// A seed row participates in the payload / validation only once it names a
// container; blank rows are ignored so the operator can leave scratch rows
// around without blocking submit.
function isActiveSeedRow(row: FluidSeedRow): boolean {
  return row.container.trim() !== "";
}

// A composition row counts once the operator has typed anything into it.
function isActiveCompositionRow(row: CompositionSeedRow): boolean {
  return row.component.trim() !== "" || row.volume.trim() !== "";
}

function parseNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

// Validate operator-entered seed rows, returning human-readable messages
// (empty array === valid). Mirrors the server's constraints so a submit is
// blocked inline rather than round-tripping to a 4xx:
//   - a named container needs a finite, non-negative volume,
//   - composition components need a name and finite, non-negative volume,
//   - when composition rows exist, they must sum to the row's volume,
//   - no two active rows may name the same container.
export function validateSeedRows(seeds: FluidSeedRow[]): string[] {
  const errors: string[] = [];
  const seen = new Map<string, number>();

  seeds.forEach((row, index) => {
    if (!isActiveSeedRow(row)) return;
    const label = row.container.trim();
    const rowRef = `Container "${label}"`;

    const previous = seen.get(label);
    if (previous !== undefined) {
      errors.push(`${rowRef} appears in more than one row (rows ${previous + 1} and ${index + 1}).`);
    } else {
      seen.set(label, index);
    }

    const volume = parseNumber(row.volume);
    if (volume === null) {
      errors.push(`${rowRef} needs a volume in µL.`);
    } else if (volume < 0) {
      errors.push(`${rowRef} volume must be zero or greater.`);
    }

    const activeComposition = row.composition.filter(isActiveCompositionRow);
    let componentTotal = 0;
    let componentValid = true;
    const seenComponents = new Set<string>();
    for (const component of activeComposition) {
      const componentName = component.component.trim();
      if (componentName === "") {
        errors.push(`${rowRef} has a composition amount with no component name.`);
        componentValid = false;
      } else if (seenComponents.has(componentName)) {
        // The payload is a map keyed by component name, so a duplicate row
        // would silently overwrite the earlier one and the server would then
        // reject the submit on a composition-sum mismatch this validator
        // claimed was fine.
        errors.push(`${rowRef} lists component "${componentName}" more than once.`);
        componentValid = false;
      } else {
        seenComponents.add(componentName);
      }
      const amount = parseNumber(component.volume);
      if (amount === null) {
        errors.push(`${rowRef} component "${component.component.trim() || "?"}" needs a volume in µL.`);
        componentValid = false;
      } else if (amount < 0) {
        errors.push(`${rowRef} component "${component.component.trim() || "?"}" volume must be zero or greater.`);
        componentValid = false;
      } else {
        componentTotal += amount;
      }
    }

    if (
      activeComposition.length > 0
      && componentValid
      && volume !== null
      && volume >= 0
      && !numbersClose(componentTotal, volume)
    ) {
      errors.push(
        `${rowRef} composition sums to ${componentTotal} µL but the volume is ${volume} µL.`,
      );
    }
  });

  return errors;
}

function numbersClose(a: number, b: number): boolean {
  const tolerance = Math.max(VOLUME_TOLERANCE_UL, Math.abs(b) * 1e-9);
  return Math.abs(a - b) <= tolerance;
}

// Assemble the `initial_state.fluids` payload from valid seed rows. Assumes
// `validateSeedRows` has already passed; blank rows are skipped, a row with
// no composition rows omits `composition` entirely (the server then labels
// its volume "unknown"), and a row with composition rows sends the parsed
// component map. An empty result is `{}` — the pre-Feature-07b behavior.
export function buildSeedFluids(seeds: FluidSeedRow[]): Record<string, FluidSeedItem> {
  const fluids: Record<string, FluidSeedItem> = {};
  for (const row of seeds) {
    if (!isActiveSeedRow(row)) continue;
    const container = row.container.trim();
    const volume = parseNumber(row.volume) ?? 0;
    const activeComposition = row.composition.filter(isActiveCompositionRow);
    if (activeComposition.length === 0) {
      fluids[container] = { volume_ul: volume };
      continue;
    }
    const composition: Record<string, number> = {};
    for (const component of activeComposition) {
      composition[component.component.trim()] = parseNumber(component.volume) ?? 0;
    }
    fluids[container] = { volume_ul: volume, composition };
  }
  return fluids;
}
