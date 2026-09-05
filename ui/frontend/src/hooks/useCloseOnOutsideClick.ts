import { RefObject, useEffect } from 'react';

/**
 * Close an open dropdown when the user presses outside it or hits Escape.
 *
 * Watches `mousedown`/`touchstart` on the document rather than the
 * trigger's `blur`. A blur-plus-timer approach loses any click whose
 * mouse-down → mouse-up gap outlasts the timer (a slow click, a remote
 * desktop, laggy input): the menu is unmounted before the click lands, so
 * the item's handler never runs and nothing is reported anywhere. Watching
 * the pointer directly has no such window — the menu only closes when the
 * press is genuinely outside it.
 *
 * Listeners are registered only while `open` is true.
 */
export function useCloseOnOutsideClick(
  containerRef: RefObject<HTMLElement | null>,
  open: boolean,
  onClose: () => void,
): void {
  useEffect(() => {
    if (!open) return undefined;

    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      const container = containerRef.current;
      if (container && !container.contains(event.target as Node)) {
        onClose();
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('touchstart', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('touchstart', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [containerRef, open, onClose]);
}
