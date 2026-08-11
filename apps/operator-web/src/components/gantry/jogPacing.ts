// Pacing for hold-to-jog. GRBL acks a jog command when it is queued in its
// planner, not when the motion finishes, so a client that sends on a fixed
// interval while the button is held can build a backlog that keeps the
// gantry moving long after release. Held jogs therefore keep one request in
// flight and pace repeats to the segment's execution time. Distinct presses
// are never paced — each press sends its first jog immediately.

export const JOG_INTERVAL_MS = 150;

// Server-side jog feed default (mm/min); see GantrySession.jog.
export const JOG_FEED_MM_PER_MIN = 2000;

export const jogSegmentMs = (x: number, y: number, z: number) =>
  (Math.sqrt(x * x + y * y + z * z) / JOG_FEED_MM_PER_MIN) * 60_000;

// The 0.8 factor sends the next segment just before the current one
// finishes so GRBL blends them smoothly without accumulating a backlog.
export const jogPaceMs = (x: number, y: number, z: number) =>
  Math.max(JOG_INTERVAL_MS, jogSegmentMs(x, y, z) * 0.8);

// A sleep that can be cut short (on button release) so the held-jog pump
// exits promptly instead of holding its slot for the rest of the pace.
export type JogPacer = {
  sleep: (ms: number) => Promise<void>;
  wake: () => void;
};

export function createJogPacer(): JogPacer {
  let wake: (() => void) | null = null;
  return {
    sleep(ms: number) {
      return new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer);
          wake = null;
          resolve();
        };
        const timer = setTimeout(finish, ms);
        wake = finish;
      });
    },
    wake() {
      wake?.();
    },
  };
}
