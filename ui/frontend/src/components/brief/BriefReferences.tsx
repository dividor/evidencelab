import React from 'react';
import { SourceReference } from '../../types/api';
import { BriefReference, BriefReferenceGroup, ReferenceGrouping } from './briefTypes';
import type { LinkTarget } from '../../utils/exportResultsToDocx';

/** Where the Word export's links point. */
export const WORD_LINK_OPTIONS: Array<{ value: LinkTarget; label: string; title: string }> = [
  {
    value: 'source',
    label: 'Source document',
    title: "Links open each document at its source (its own PDF or report page), at the cited page",
  },
  {
    value: 'evidence_lab',
    label: 'Evidence Lab',
    title: 'Links open the copy of each document in Evidence Lab, at the cited page',
  },
];

/** Radio buttons: where the Word export's links point. */
const WordLinkChoice: React.FC<{ value: LinkTarget; onChange: (value: LinkTarget) => void }> = ({
  value,
  onChange,
}) => (
  <div className="brief-footnotes-word-links" role="radiogroup" aria-label="Word export links point to">
    <span className="brief-footnotes-word-links-label">Word links to</span>
    {WORD_LINK_OPTIONS.map((option) => (
      <label className="brief-footnotes-group-toggle" key={option.value} title={option.title}>
        <input
          type="radio"
          name="brief-word-link-target"
          checked={value === option.value}
          onChange={() => onChange(option.value)}
        />
        {option.label}
      </label>
    ))}
  </div>
);

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

type SourceClick = (source: SourceReference) => void;

const clickSource = (onSourceClick: SourceClick, source?: SourceReference | null) =>
  (e: React.MouseEvent) => {
    e.preventDefault();
    if (source) onSourceClick(source);
  };

// "[1] Title, p.32" — or just "[1] Title" for a document-level reference.
const FlatRow: React.FC<{ reference: BriefReference; onSourceClick: SourceClick }> = ({
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

// "Title, [1] p. 32, [2] p. 56": the document once, then each of its numbers,
// exactly as the API grouped them.
const GroupedRow: React.FC<{
  group: BriefReferenceGroup;
  sourceOf: (sourceId: string) => SourceReference | null | undefined;
  onSourceClick: SourceClick;
}> = ({ group: g, sourceOf, onSourceClick }) => (
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
              onClick={clickSource(onSourceClick, sourceOf(c.sourceId))}
            >
              {c.n}
            </a>
          </span>
        )}
        {c.page ? (
          <a
            href="#"
            className="brief-footnote-page-link"
            onClick={clickSource(onSourceClick, sourceOf(c.sourceId))}
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
 * toggles. The list, its numbers and its grouping are exactly what the API
 * returned for the brief; choosing a grouping asks the API to renumber the
 * brief and the list is re-rendered from its reply.
 */
export const BriefReferences: React.FC<{
  references: BriefReference[];
  groups: BriefReferenceGroup[];
  grouping: ReferenceGrouping;
  onGroupingChange: (grouping: ReferenceGrouping) => void;
  onSourceClick: SourceClick;
  /** Where the Word export's links point; the choice is shown when set. */
  wordLinkTarget?: LinkTarget;
  onWordLinkTargetChange?: (value: LinkTarget) => void;
}> = ({
  references,
  groups,
  grouping,
  onGroupingChange,
  onSourceClick,
  wordLinkTarget,
  onWordLinkTargetChange,
}) => {
  if (references.length === 0) return null;
  const sourceOf = (sourceId: string) => references.find((r) => r.sourceId === sourceId)?.source;
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
        {wordLinkTarget && onWordLinkTargetChange && (
          <WordLinkChoice value={wordLinkTarget} onChange={onWordLinkTargetChange} />
        )}
      </div>
      <div className="brief-footnotes-list">
        {grouping === 'document-multiple'
          ? groups.map((g) => (
              <GroupedRow
                key={g.docId || g.title}
                group={g}
                sourceOf={sourceOf}
                onSourceClick={onSourceClick}
              />
            ))
          : references.map((r) => (
              <FlatRow key={r.n} reference={r} onSourceClick={onSourceClick} />
            ))}
      </div>
    </section>
  );
};
