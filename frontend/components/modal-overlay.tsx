"use client";
import { ReactNode, useEffect, useRef } from "react";

/** Keep keyboard review inside the dialog and return focus to its opener. */
export default function ModalOverlay({
  children,
  onClose,
  returnFocusSelector,
}: {
  children: ReactNode;
  onClose: () => void;
  returnFocusSelector?: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  const previous = useRef<HTMLElement | null>(
    typeof document === "undefined"
      ? null
      : (document.activeElement as HTMLElement),
  );
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const root = element.current;
    const focusables = () =>
      Array.from(
        root?.querySelectorAll<HTMLElement>(
          'button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]',
        ) || [],
      ).filter((el) => el.offsetParent !== null);
    const first = focusables();
    if (!root?.contains(document.activeElement)) first[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables(),
        first = items[0],
        last = items.at(-1);
      if (!first) {
        event.preventDefault();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !root?.contains(document.activeElement))
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !root?.contains(document.activeElement))
      ) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      const target = previous.current;
      if (
        target?.isConnected &&
        target !== document.body &&
        !root?.contains(target)
      )
        target.focus();
      else if (returnFocusSelector)
        document.querySelector<HTMLElement>(returnFocusSelector)?.focus();
    };
  }, []);
  return (
    <div ref={element} className="modal-backdrop">
      {children}
    </div>
  );
}
