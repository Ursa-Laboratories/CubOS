import React, { useCallback, useRef, useState } from "react";
import { ConfirmDialog, type ConfirmOptions } from "./ConfirmDialog";

type PendingConfirm = { options: ConfirmOptions; resolve: (confirmed: boolean) => void };

/**
 * Promise-based confirmation. Returns a `confirm` function that resolves
 * true/false with the user's choice, and the dialog element to render:
 *
 *   const [requestConfirm, confirmDialog] = useConfirm();
 *   ...
 *   if (!(await requestConfirm("Discard unsaved changes?"))) return;
 *   ...
 *   return <div>...{confirmDialog}</div>;
 */
export function useConfirm(): [
  (request: string | ConfirmOptions) => Promise<boolean>,
  React.ReactNode,
] {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const pendingRef = useRef<PendingConfirm | null>(null);

  const confirm = useCallback((request: string | ConfirmOptions) => {
    const options = typeof request === "string" ? { message: request } : request;
    // A new request while one is open cancels the earlier one.
    pendingRef.current?.resolve(false);
    return new Promise<boolean>((resolve) => {
      const next = { options, resolve };
      pendingRef.current = next;
      setPending(next);
    });
  }, []);

  const settle = useCallback((confirmed: boolean) => {
    pendingRef.current?.resolve(confirmed);
    pendingRef.current = null;
    setPending(null);
  }, []);

  const dialog = pending ? (
    <ConfirmDialog
      {...pending.options}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null;

  return [confirm, dialog];
}
