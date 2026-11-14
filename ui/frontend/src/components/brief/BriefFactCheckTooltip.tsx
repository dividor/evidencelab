import React, { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { FactMarkHover } from './useBriefFactCheck';

// The judge's reasoning for the highlighted passage under the pointer, shown
// as a card beside it. Rendered into the body so it floats over everything,
// and placed above the passage when there is no room below.
export const BriefFactCheckTooltip: React.FC<{ hover: FactMarkHover | null }> = ({ hover }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!hover || !ref.current) {
      setTop(null);
      return;
    }
    const height = ref.current.offsetHeight;
    const below = hover.rect.bottom + 8;
    const fits = below + height <= window.innerHeight - 8;
    setTop(fits ? below : Math.max(8, hover.rect.top - height - 8));
  }, [hover]);
  if (!hover) return null;
  const { mark, rect } = hover;
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - 376));
  return createPortal(
    <div
      ref={ref}
      className="brief-fact-tooltip"
      role="tooltip"
      style={{ top: top ?? rect.bottom + 8, left, visibility: top === null ? 'hidden' : 'visible' }}
    >
      <div className={`brief-fact-tooltip-verdict brief-fact-mark-${mark.verdict}`}>
        {mark.verdict_label}
        {mark.confidence != null && (
          <span className="brief-fact-tooltip-confidence">
            {Math.round(mark.confidence * 100)}% confidence
          </span>
        )}
      </div>
      {mark.problems.length > 0 && (
        <ul className="brief-fact-tooltip-problems">
          {mark.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <p className="brief-fact-tooltip-explanation">{mark.explanation}</p>
      <div className="brief-fact-tooltip-foot">
        Judged against the sources cited as [{mark.citations}]
        {mark.quote_not_in_source ? ' · quote not found in source' : ''}
      </div>
    </div>,
    document.body,
  );
};
