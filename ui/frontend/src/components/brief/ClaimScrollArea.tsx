import React, { useLayoutEffect, useRef, useState } from 'react';

/** One scroll area keeps the claim and all source excerpts in reading order. */
export function ClaimScrollArea({ children }: { children: React.ReactNode }) {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  const measure = () => {
    const el = viewport.current!;
    setMore(el.scrollHeight - el.clientHeight - el.scrollTop > 2);
  };
  useLayoutEffect(() => {
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport.current!);
    observer.observe(content.current!);
    return () => observer.disconnect();
  }, []);
  return <>
    <div className="claim-scroll-area" ref={viewport} tabIndex={0} role="region"
      aria-label="Claim assessment and sources" onScroll={measure}>
      <div ref={content}>{children}</div>
    </div>
    {more && <div className="claim-scroll-footer">
      <button type="button" onClick={() => {
        const el = viewport.current!;
        el.scrollBy({ top: el.clientHeight * .75, behavior: 'smooth' });
      }}>See more <span aria-hidden="true">↓</span></button>
    </div>}
  </>;
}
