import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useCalibrationAutoRecovery } from "./useCalibrationAutoRecovery";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("generates unique correlated IDs without requiring secure-context randomUUID", () => {
  const random = vi.fn((bytes: Uint8Array) => bytes.fill(1));
  vi.stubGlobal("crypto", { getRandomValues: random, randomUUID: undefined });
  const { result } = renderHook(() => useCalibrationAutoRecovery(true));
  const first = result.current.issueJogId();
  const second = result.current.issueJogId();
  expect(first).toMatch(/^calibration-/);
  expect(first).not.toBe(second);
  expect(first!.length).toBeLessThanOrEqual(128);
  expect(random).toHaveBeenCalledTimes(2);
});

it("keeps IDs unique when browser crypto is unavailable", () => {
  vi.stubGlobal("crypto", undefined);
  const { result } = renderHook(() => useCalibrationAutoRecovery(true));
  expect(result.current.issueJogId()).not.toBe(result.current.issueJogId());
});

it("retains once-only attempts across renders and revokes ownership on cancellation/new lifetime", () => {
  const { result, rerender } = renderHook(({ open }) => useCalibrationAutoRecovery(open), { initialProps: { open: true } });
  const id = result.current.issueJogId()!;
  expect(result.current.claimFault(id)).toBe(true);
  rerender({ open: true });
  expect(result.current.claimFault(id)).toBe(false);
  const lifetime = result.current.lifetime;
  act(() => result.current.cancel());
  expect(result.current.lifetime).toBe(lifetime);
  expect(result.current.claimFault(id)).toBe(false);
  rerender({ open: false });
  expect(result.current.issueJogId()).toBeUndefined();
  rerender({ open: true });
  expect(result.current.lifetime).toBeGreaterThan(lifetime);
  expect(result.current.claimFault(id)).toBe(false);
});

it("revokes old IDs on disconnect while allowing a fresh user jog after reconnect", () => {
  const { result, rerender } = renderHook(({ connected }) => useCalibrationAutoRecovery(true, connected), { initialProps: { connected: true } });
  const old = result.current.issueJogId()!;
  rerender({ connected: false });
  rerender({ connected: true });
  expect(result.current.claimFault(old)).toBe(false);
  const fresh = result.current.issueJogId()!;
  expect(result.current.claimFault(fresh)).toBe(true);
});
