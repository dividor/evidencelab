import React, { useCallback, useEffect, useLayoutEffect, useRef } from 'react';

/** Height (px) a field grows to before it scrolls inside instead. */
export const AUTO_GROW_MAX_HEIGHT = 240;

export interface AutoGrowTextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Grow to this height (px), then scroll inside. */
  maxHeight?: number;
  /** Enter submits the enclosing form; Shift+Enter inserts a line break. */
  submitOnEnter?: boolean;
}

/**
 * A textarea that grows with its content so a long prompt stays fully
 * visible, up to `maxHeight`, after which it scrolls. `rows` sets the
 * starting height, as on a plain textarea.
 */
export const AutoGrowTextarea = ({
  maxHeight = AUTO_GROW_MAX_HEIGHT,
  submitOnEnter = false,
  onKeyDown,
  value,
  ...rest
}: AutoGrowTextareaProps) => {
  const ref = useRef<HTMLTextAreaElement>(null);

  const fit = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    // Borders sit outside scrollHeight but inside the box (box-sizing: border-box).
    const borders = el.offsetHeight - el.clientHeight;
    const needed = el.scrollHeight + borders;
    const capped = needed > maxHeight;
    el.style.height = `${capped ? maxHeight : needed}px`;
    el.style.overflowY = capped ? 'auto' : 'hidden';
  }, [maxHeight]);

  useLayoutEffect(fit, [value, fit]);

  // Re-measure when the field changes width or becomes visible (display: none → block),
  // since neither changes `value`.
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(() => requestAnimationFrame(fit));
    observer.observe(el);
    return () => observer.disconnect();
  }, [fit]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    onKeyDown?.(event);
    const plainEnter =
      submitOnEnter && event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing;
    if (!plainEnter || event.defaultPrevented) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };

  return <textarea ref={ref} value={value} onKeyDown={handleKeyDown} {...rest} />;
};
