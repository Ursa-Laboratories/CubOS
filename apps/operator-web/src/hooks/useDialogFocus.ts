import { useEffect, type KeyboardEvent, type RefObject } from "react";

export function useDialogFocus(
  initialFocus: RefObject<HTMLElement | null>,
  returnFocus?: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    const previousFocus = returnFocus?.current ?? document.activeElement;
    initialFocus.current?.focus();
    return () => {
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus();
      }
    };
  }, [initialFocus, returnFocus]);

  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
      "button, input, select, textarea, a[href], [tabindex]",
    )).filter((element) => element.tabIndex >= 0 && !element.matches(":disabled, [hidden]"));
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  };
}
