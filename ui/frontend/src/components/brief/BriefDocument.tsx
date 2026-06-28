import React, { useState } from 'react';
import { SearchResult, SourceReference } from '../../types/api';
import { CitedMarkdown, CitedReferences } from '../citations/CitedContent';
import { BriefSection } from './briefTypes';
import { UseBriefReturn } from './useBrief';

const tagClass = (tag: string): string => `brief-tag brief-tag-${tag.toLowerCase()}`;

interface SectionViewProps {
  section: BriefSection;
  num: string;
  brief: UseBriefReturn;
  onSourceClick: (source: SourceReference) => void;
}

// A textarea for editing a section's heading guidance / regenerating, shown for
// both pending sections (research with guidance) and done sections (re-research).
const GuidancePanel: React.FC<{ section: BriefSection; brief: UseBriefReturn }> = ({
  section,
  brief,
}) => {
  const isPending = section.status === 'pending';
  return (
    <div className="brief-regen-panel">
      <div className="brief-regen-title">
        {isPending ? 'Research' : 'Regenerate'} “{section.title}”
      </div>
      <textarea
        value={brief.regenText}
        onChange={(e) => brief.setRegenText(e.target.value)}
        rows={2}
        placeholder="Optional: add focus or guidance — e.g. ‘emphasise sub-Saharan Africa & 2020 onward’"
      />
      <div className="brief-regen-actions">
        <button
          className="brief-btn brief-btn-primary"
          onClick={() => brief.regenerate(section.id, brief.regenText.trim() || null)}
        >
          {isPending ? 'Research section' : 'Re-research section'}
        </button>
        <button className="brief-btn brief-btn-secondary" onClick={brief.closeRegen}>
          Cancel
        </button>
      </div>
    </div>
  );
};

const BriefSectionView: React.FC<SectionViewProps> = ({ section, num, brief, onSourceClick }) => {
  const [editing, setEditing] = useState(false);
  const panelOpen = brief.regenFor === section.id;
  const anyResearching = brief.sections.some((s) => s.status === 'researching');
  const isDone = section.status === 'done';

  return (
    <section className={`brief-doc-section${section.level === 2 ? ' brief-doc-section-sub' : ''}`}>
      <div className="brief-doc-section-head">
        <span className="brief-doc-section-num">{num}</span>
        <input
          className="brief-doc-section-title"
          value={section.title}
          onChange={(e) => brief.editTitle(section.id, e.target.value)}
          onBlur={brief.commitEdits}
        />
        {isDone && (
          <>
            <button className="brief-regen-btn" onClick={() => setEditing((v) => !v)}>
              {editing ? '✓ Done' : '✎ Edit text'}
            </button>
            <button className="brief-regen-btn" onClick={() => brief.openRegen(section.id)}>
              ↻ Regenerate
            </button>
          </>
        )}
      </div>

      {panelOpen && <GuidancePanel section={section} brief={brief} />}

      {section.status === 'pending' && !panelOpen && (
        <div className="brief-pending">
          <span className="brief-pending-dot" /> Awaiting deep research
          {!anyResearching && (
            <button
              className="brief-btn brief-btn-secondary brief-research-one-btn"
              onClick={() => brief.openRegen(section.id)}
              disabled={section.sample}
              title={section.sample ? 'Edit this heading before researching it' : undefined}
            >
              ✦ Research this section
            </button>
          )}
        </div>
      )}

      {section.status === 'researching' && (
        <div className="brief-researching">
          <div className="brief-researching-head">
            <span className="brief-spinner" />
            <span className="brief-researching-label">Researching this section</span>
            <span className="brief-researching-pct">{section.progress}%</span>
          </div>
          <div className="brief-activity">
            {section.activity.map((ev, idx) => (
              <div className="brief-activity-row" key={`${ev.tag}-${idx}`}>
                <span className={tagClass(ev.tag)}>{ev.tag}</span>
                <span>{ev.text}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {isDone && (
        <>
          {editing ? (
            <textarea
              className="brief-edit-textarea"
              value={section.content}
              onChange={(e) => brief.editContent(section.id, e.target.value)}
              onBlur={brief.commitEdits}
              rows={Math.min(28, Math.max(8, section.content.split('\n').length + 2))}
            />
          ) : (
            <div className="brief-doc-content">
              <CitedMarkdown
                content={section.content}
                sources={section.sources}
                onSourceClick={onSourceClick}
              />
            </div>
          )}
          <CitedReferences
            content={section.content}
            sources={section.sources}
            onSourceClick={onSourceClick}
            collapsible
            labelPrefix="Evidence"
            className="brief-evidence"
          />
        </>
      )}
    </section>
  );
};

interface BriefDocumentProps {
  brief: UseBriefReturn;
  onResultClick?: (result: SearchResult) => void;
}

export const BriefDocument: React.FC<BriefDocumentProps> = ({ brief, onResultClick }) => {
  const { sections, numbers, references } = brief;

  // Convert an assistant SourceReference into the SearchResult the app's
  // document preview expects (same mapping the Research Assistant uses).
  const handleSourceClick = (source: SourceReference) => {
    if (!onResultClick) return;
    onResultClick({
      chunk_id: source.chunkId,
      doc_id: source.docId,
      title: source.title,
      text: source.text,
      page_num: source.page || 1,
      score: source.score,
      headings: source.headings || [],
      bbox: source.bbox,
      metadata: {},
    });
  };

  return (
    <div className="brief-doc">
      <div className="brief-doc-header">
        <div className="brief-eyebrow">EVIDENCE BRIEF</div>
        <input
          className="brief-doc-title-input"
          value={brief.briefTitle}
          onChange={(e) => brief.setBriefTitle(e.target.value)}
          onBlur={brief.commitEdits}
          aria-label="Brief title"
        />
        <div className="brief-doc-meta">
          <span>{sections.length} sections</span>
          <span>·</span>
          <span>{brief.totalSources} sources synthesised</span>
        </div>
      </div>

      {sections.map((s, i) => (
        <BriefSectionView
          key={s.id}
          section={s}
          num={numbers[i]}
          brief={brief}
          onSourceClick={handleSourceClick}
        />
      ))}

      {references.length > 0 && (
        <section className="brief-footnotes">
          <h2 className="brief-footnotes-title">Footnotes</h2>
          <div className="brief-footnotes-sub">
            All {references.length} cited documents, compiled across sections
          </div>
          <div className="brief-footnotes-list">
            {references.map((r) => (
              <div className="brief-footnote-row" key={r.n}>
                <a
                  href="#"
                  className="brief-footnote-link"
                  onClick={(e) => {
                    e.preventDefault();
                    handleSourceClick(r.source);
                  }}
                >
                  <span className="citation-doc-group">
                    <span className="ai-summary-citation">{r.n}</span>
                  </span>
                  <span className="brief-footnote-text">
                    {r.title}
                    {r.page ? ` p.${r.page}` : ''}
                  </span>
                </a>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};
