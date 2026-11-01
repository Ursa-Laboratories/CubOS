import type { ProtocolStep } from "../../types";

function replaceWellTarget(value: unknown, sourceTarget: string, targetTarget: string): unknown {
  if (typeof value === "string") return value === sourceTarget ? targetTarget : value;
  if (Array.isArray(value)) {
    return value.map((item) => replaceWellTarget(item, sourceTarget, targetTarget));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        replaceWellTarget(item, sourceTarget, targetTarget),
      ]),
    );
  }
  return value;
}

export function expandStepsAcrossWells(
  steps: ProtocolStep[],
  startStep: number,
  endStep: number,
  labwareKey: string,
  templateWell: string,
  targetWells: string[],
): ProtocolStep[] {
  if (startStep < 1 || endStep < startStep || endStep > steps.length) {
    throw new Error(`Choose a valid step range between 1 and ${steps.length}.`);
  }
  if (!labwareKey || !templateWell || targetWells.length === 0) {
    throw new Error("Choose labware, a template well, and at least one target well.");
  }
  const sourceTarget = `${labwareKey}.${templateWell}`;
  const block = steps.slice(startStep - 1, endStep);
  const expanded = targetWells.flatMap((well) => {
    const targetTarget = `${labwareKey}.${well}`;
    return block.map((step) => {
      const args = replaceWellTarget(
        structuredClone(step.args), sourceTarget, targetTarget,
      ) as Record<string, unknown>;
      if (typeof args.label === "string" && args.label.trim()) {
        args.label = `${args.label}_${well}`;
      }
      return { command: step.command, args };
    });
  });
  return [
    ...steps.slice(0, startStep - 1),
    ...expanded,
    ...steps.slice(endStep),
  ];
}
