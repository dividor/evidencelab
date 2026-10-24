import React, { useCallback, useEffect, useState } from 'react';

/** Fraction of the visible width one click scrolls by. */
export const SCROLL_STEP_FRACTION = 0.8;

interface ScrollChevronsProps {
  /** The horizontally scrolling element the chevrons control. */
  container: HTMLDivElement | null;
}

interface ScrollState {
  canScrollLeft: boolean;
  canScrollRight: boolean;
}

const readScrollState = (el: HTMLElement): ScrollState => ({
  canScrollLeft: el.scrollLeft > 0,
  // One pixel of tolerance absorbs sub-pixel layout rounding.
  canScrollRight: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
});

const Chevron: React.FC<{ direction: 'left' | 'right' }> = ({ direction }) => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
    <path
      d={direction === 'right' ? 'M5.5 2.5 11 8l-5.5 5.5' : 'M10.5 2.5 5 8l5.5 5.5'}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/**
 * Left/right chevrons that tell the reader a wide table scrolls sideways.
 *
 * The right chevron shows as soon as the table overflows; the left one appears
 * only once the reader has scrolled right. Both sit at the vertical middle of
 * the visible table and disappear when there is nothing further to reveal.
 */
export const ScrollChevrons: React.FC<ScrollChevronsProps> = ({ container }) => {
  const [state, setState] = useState<ScrollState>({ canScrollLeft: false, canScrollRight: false });

  useEffect(() => {
    if (!container) return undefined;
    const update = () => setState(readScrollState(container));
    update();
    container.addEventListener('scroll', update);
    // jsdom has no ResizeObserver; browsers do, and it is what keeps the
    // chevrons right when columns or the window change width.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    observer?.observe(container);
    const table = container.querySelector('table');
    if (table && observer) observer.observe(table);
    return () => {
      container.removeEventListener('scroll', update);
      observer?.disconnect();
    };
  }, [container]);

  const scrollBy = useCallback(
    (direction: 1 | -1) => {
      if (!container) return;
      const step = Math.round(container.clientWidth * SCROLL_STEP_FRACTION) * direction;
      container.scrollLeft = Math.max(0, container.scrollLeft + step);
      setState(readScrollState(container));
    },
    [container],
  );

  if (!container || (!state.canScrollLeft && !state.canScrollRight)) return null;

  return (
    <div className="table-scroll-chevrons">
      {state.canScrollLeft && (
        <button
          type="button"
          className="table-scroll-chevron table-scroll-chevron-left"
          aria-label="Scroll table left"
          onClick={() => scrollBy(-1)}
        >
          <Chevron direction="left" />
        </button>
      )}
      {state.canScrollRight && (
        <button
          type="button"
          className="table-scroll-chevron table-scroll-chevron-right"
          aria-label="Scroll table right"
          onClick={() => scrollBy(1)}
        >
          <Chevron direction="right" />
        </button>
      )}
    </div>
  );
};
