import React from 'react';

/**
 * Citation rendering utilities for the Ratings admin panel.
 * Extracted to keep file-level cyclomatic complexity within bounds.
 */

const CITE_SPLIT = /(\[\d+(?:\s*,\s*\d+)*\](?!\())/g;
const CITE_MATCH = /^\[(\d+(?:\s*,\s*\d+)*)\]$/;
const CITE_EXTRACT = /\[(\d+(?:,\s*\d+)*)\]/g;

const buildCitationBadge = (num: number, results: any[], i: number, j: number) => {
  const idx = num - 1;
  const r = idx >= 0 && idx < results.length ? results[idx] : null;
  if (r?.link) {
    const pageSuffix = r.page_num ? ', p.' + String(r.page_num) : '';
    const tip = (r.title || 'Untitled') + pageSuffix;
    return (
      <a key={`c${i}-${j}`} href={r.link} target="_blank" rel="noopener noreferrer"
        className="admin-citation-badge admin-citation-clickable" title={tip}
        onClick={(e) => e.stopPropagation()}>{num}</a>
    );
  }
  return <span key={`c${i}-${j}`} className="admin-citation-badge">{num}</span>;
};

export const createCitationRenderer = (results: any[]) => {
  const render = (children: React.ReactNode): React.ReactNode => {
    return React.Children.map(children, (child) => {
      if (typeof child === 'string') {
        const parts = child.split(CITE_SPLIT);
        if (parts.length === 1) return child;
        return parts.map((part, i) => {
          const m = part.match(CITE_MATCH);
          if (m) {
            return m[1].split(',').map((n, j) =>
              buildCitationBadge(parseInt(n.trim(), 10), results, i, j),
            );
          }
          return part || null;
        });
      }
      if (React.isValidElement(child) && (child.props as any).children) {
        return React.cloneElement(
          child as React.ReactElement<any>,
          {},
          render((child.props as any).children),
        );
      }
      return child;
    });
  };
  return render;
};

/** Extract all cited numbers, map to results, group by document title */
const buildGroupedRefs = (summary: string, results: any[]) => {
  const cited = new Set<number>();
  let m: RegExpExecArray | null;
  const re = new RegExp(CITE_EXTRACT.source, 'g');
  while ((m = re.exec(summary)) !== null) {
    m[1].split(',').forEach((n) => cited.add(parseInt(n.trim(), 10)));
  }
  if (cited.size === 0 || !results?.length) return [];
  const groups = new Map<string, { title: string; org?: string; year?: string; refs: { num: number; result: any }[] }>();
  const order: string[] = [];
  const sorted = Array.from(cited).sort((a, b) => a - b);
  sorted.forEach((origNum, seqIdx) => {
    const idx = origNum - 1;
    if (idx < 0 || idx >= results.length) return;
    const r = results[idx];
    const key = r.title || `result-${idx}`;
    if (!groups.has(key)) {
      groups.set(key, { title: r.title || 'Untitled', org: r.organization, year: r.year, refs: [] });
      order.push(key);
    }
    groups.get(key)!.refs.push({ num: seqIdx + 1, result: r });
  });
  return order.map((k) => groups.get(k)!);
};

/** References section matching the main search view style */
export const AdminReferences: React.FC<{ summary: string; results: any[] }> = ({ summary, results }) => {
  const groups = buildGroupedRefs(summary, results);
  if (groups.length === 0) return null;
  return (
    <div className="admin-references-section">
      <h4>References:</h4>
      {groups.map((g) => (
        <div key={g.title} className="admin-ref-group">
          <span>{g.title}{g.org && `, ${g.org}`}{g.year && `, ${g.year}`}</span>
          {' | '}
          {g.refs.map(({ num, result }, i) => (
            <React.Fragment key={num}>
              {i > 0 && ' '}
              {result.link ? (
                <a href={result.link} target="_blank" rel="noopener noreferrer"
                  className="admin-ref-link" onClick={(e) => e.stopPropagation()}>
                  <span className="admin-citation-badge admin-citation-clickable">{num}</span>
                  {result.page_num ? ` p.${result.page_num}` : ''}
                </a>
              ) : (
                <>
                  <span className="admin-citation-badge">{num}</span>
                  {result.page_num ? <span className="admin-ref-page"> p.{result.page_num}</span> : ''}
                </>
              )}
            </React.Fragment>
          ))}
        </div>
      ))}
    </div>
  );
};
