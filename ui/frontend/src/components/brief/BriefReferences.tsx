import React from 'react';
import { SourceReference } from '../../types/api';
import { GlobalRef } from './briefCitations';
import { ReferenceGrouping } from './briefTypes';

// The two "Group by document" options offered above the References list. They
// are exclusive: ticking one clears the other, and clearing both returns to
// one row per cited passage.
export const REFERENCE_GROUPING_LABELS: Record<
  Exclude<ReferenceGrouping, 'passage'>,
  string
> = {
  'document-multiple': 'Group by document (multiple per document)',
  'document-single': 'Group by document (single per document)',
};

const GROUPING_OPTIONS = Object.keys(REFERENCE_GROUPING_LABELS) as Array<
  keyof typeof REFERENCE_GROUPING_LABELS
>;

interface DocCite {
  n: number;
  page: number;
  source: SourceReference;
}

interface DocGroup {
  key: string;
  title: string;
  cites: DocCite[];
}

// One row per document: its title, then each citation number pointing into it
// with that number's page — "Title, [1] p. 32, [2] p. 56". No excerpts.
export const groupReferencesByDoc = (refs: GlobalRef[]): DocGroup[] => {
  const byDoc = new Map<string, DocGroup>();
  // Numbers are per cited passage, so a document collects each of its own
  // numbers with the page that number points at.
  for (const r of refs) {
    const key = r.source.docId || r.title;
    const cite = { n: r.n, page: r.page ?? 0, source: r.source };
    const found = byDoc.get(key);
    if (found) found.cites.push(cite);
    else byDoc.set(key, { key, title: r.title, cites: [cite] });
  }
  byDoc.forEach((g) => g.cites.sort((a, b) => a.page - b.page || a.n - b.n));
  return Array.from(byDoc.values());
};

type SourceClick = (source: SourceReference) => void;

const clickSource = (onSourceClick: SourceClick, source: SourceReference) =>
  (e: React.MouseEvent) => {
    e.preventDefault();
    onSourceClick(source);
  };

// "[1] Title, p.32" — or just "[1] Title" for a document-level reference.
const FlatRow: React.FC<{ reference: GlobalRef; onSourceClick: SourceClick }> = ({
  reference: r,
  onSourceClick,
}) => (
  <div className="brief-footnote-row">
    <a href="#" className="brief-footnote-link" onClick={clickSource(onSourceClick, r.source)}>
      <span className="citation-doc-group">
        <span className="ai-summary-citation">{r.n}</span>
      </span>
      <span className="brief-footnote-text">
        {r.title}
        {r.page ? `, p.${r.page}` : ''}
      </span>
    </a>
  </div>
);

// "Title, [1] p. 32, [2] p. 56": the document once, then each of its numbers.
const GroupedRow: React.FC<{ group: DocGroup; onSourceClick: SourceClick }> = ({
  group: g,
  onSourceClick,
}) => (
  <div className="brief-footnote-group">
    <span className="brief-footnote-text">{g.title}</span>
    {g.cites.map((c, i) => (
      <span className="brief-footnote-cite" key={`${c.n}-${c.page}-${i}`}>
        {/* The number is shown once per run of the same citation, so a
            document cited from many pages reads "[1] p. 9, p. 11" rather
            than repeating "[1]". */}
        {(i === 0 || g.cites[i - 1].n !== c.n) && (
          <span className="citation-doc-group">
            <a
              href="#"
              className="ai-summary-citation"
              onClick={clickSource(onSourceClick, c.source)}
            >
              {c.n}
            </a>
          </span>
        )}
        {c.page ? (
          <a
            href="#"
            className="brief-footnote-page-link"
            onClick={clickSource(onSourceClick, c.source)}
          >
            {` p. ${c.page}`}
          </a>
        ) : null}
      </span>
    ))}
  </div>
);

/**
 * The compiled References list at the end of a brief, with the grouping
 * toggles. The grouping also decides the citation numbering (see
 * buildGlobalCitations), so switching it renumbers the inline `[n]` markers
 * as well as this list.
 */
export const BriefReferences: React.FC<{
  references: GlobalRef[];
  grouping: ReferenceGrouping;
  onGroupingChange: (grouping: ReferenceGrouping) => void;
  onSourceClick: SourceClick;
}> = ({ references, grouping, onGroupingChange, onSourceClick }) => {
  if (references.length === 0) return null;
  return (
    <section className="brief-footnotes">
      <div className="brief-footnotes-head">
        <h2 className="brief-footnotes-title">References</h2>
        <div className="brief-footnotes-group-toggles">
          {GROUPING_OPTIONS.map((option) => (
            <label className="brief-footnotes-group-toggle" key={option}>
              <input
                type="checkbox"
                checked={grouping === option}
                onChange={(e) => onGroupingChange(e.target.checked ? option : 'passage')}
              />
              {REFERENCE_GROUPING_LABELS[option]}
            </label>
          ))}
        </div>
      </div>
      <div className="brief-footnotes-list">
        {grouping === 'document-multiple'
          ? groupReferencesByDoc(references).map((g) => (
              <GroupedRow key={g.key} group={g} onSourceClick={onSourceClick} />
            ))
          : references.map((r) => (
              <FlatRow key={r.n} reference={r} onSourceClick={onSourceClick} />
            ))}
      </div>
    </section>
  );
};
