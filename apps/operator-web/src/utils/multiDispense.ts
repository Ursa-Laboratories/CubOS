export function multiDispenseErrors(args: Record<string, unknown>): string[] {
  const { destinations, volumes } = args;
  if (!Array.isArray(destinations) || !Array.isArray(volumes)) {
    return ["Destinations and volumes must be lists. Correct them in raw YAML."];
  }
  if (!destinations.length && !volumes.length) return ["Add at least one destination and volume."];
  const errors: string[] = [];
  if (destinations.length !== volumes.length) errors.push("Each destination needs a matching volume.");
  for (let i = 0; i < Math.max(destinations.length, volumes.length); i++) {
    if (typeof destinations[i] !== "string" || !destinations[i].trim()) {
      errors.push(`Row ${i + 1}: enter a destination.`);
    }
    if (typeof volumes[i] !== "number" || !Number.isFinite(volumes[i]) || volumes[i] <= 0) {
      errors.push(`Row ${i + 1}: enter a finite volume greater than 0 µL.`);
    }
  }
  return errors;
}
