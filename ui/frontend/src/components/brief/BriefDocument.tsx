import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BriefSection } from './briefTypes';
import { UseBriefReturn } from './useBrief';

const tagClass = (tag: string): string => `brief-tag brief-tag-${tag.toLowerCase()}`;

interface SectionViewProps {
  section: BriefSection;
  num: string;
  brief: UseBriefReturn;
}

const BriefSectionView: React.FC<SectionViewProps> = ({ section, num, brief }) => {
  const regenOpen = brief.regenFor === section.id;
  const anyResearching = brief.sections.some((s) => s.status === 'researching');
  return (
    <section className={`brief-doc-section${section.level === 2 ? ' brief-doc-section-sub' : ''}`}>
      <div className="brief-doc-section-head">
        <span className="brief-doc-section-num">{num}</span>
        <input
          className="brief-doc-section-title"
          value={section.title}
          onChange={(e) => brief.editTitle(section.id, e.target.value)}
        />
        {section.status === 'done' && (
          <button className="brief-regen-btn" onClick={() => brief.openRegen(section.id)}>
            ↻ Regenerate
          </button>
        )}
      </div>

      {regenOpen && (
        <div className="brief-regen-panel">
          <div className="brief-regen-title">Regenerate “{section.title}”</div>
          <textarea
            value={brief.regenText}
            onChange={(e) => brief.setRegenText(e.target.value)}
            rows={2}
            placeholder="Optional: add focus or context — e.g. ‘emphasise sub-Saharan Africa & 2020 onward’"
          />
          <div className="brief-regen-actions">
            <button
              className="brief-btn brief-btn-primary"
              onClick={() => brief.regenerate(section.id, brief.regenText.trim() || null)}
            >
              Re-research section
            </button>
            <button className="brief-btn brief-btn-secondary" onClick={brief.closeRegen}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {section.status === 'pending' && (
        <div className="brief-pending">
          <span className="brief-pending-dot" /> Awaiting deep research
          {!anyResearching && (
            <button
              className="brief-btn brief-btn-secondary brief-research-one-btn"
              onClick={() => brief.researchSection(section.id)}
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

      {section.status === 'done' && (
        <>
          <div className="brief-doc-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.content}</ReactMarkdown>
          </div>
          {section.sources.length > 0 && (
            <div className="brief-sources">
              <div className="brief-sources-label">
                Sources · {section.sources.length} synthesised
              </div>
              <div className="brief-sources-list">
                {section.sources.map((src) => (
                  <div className="brief-source-row" key={src.chunkId}>
                    <span className="brief-source-n">{src.index ?? '•'}</span>
                    <span className="brief-source-text">
                      {src.title}
                      {src.page ? <span className="brief-source-page"> (p. {src.page})</span> : null}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
};

interface BriefDocumentProps {
  brief: UseBriefReturn;
}

export const BriefDocument: React.FC<BriefDocumentProps> = ({ brief }) => {
  const { sections, numbers, references } = brief;
  return (
    <div className="brief-doc">
      <div className="brief-doc-header">
        <div className="brief-eyebrow">EVIDENCE BRIEF</div>
        <input
          className="brief-doc-title-input"
          value={brief.briefTitle}
          onChange={(e) => brief.setBriefTitle(e.target.value)}
          onBlur={brief.commitTitle}
          aria-label="Brief title"
        />
        <div className="brief-doc-meta">
          <span>{sections.length} sections</span>
          <span>·</span>
          <span>{brief.totalSources} sources synthesised</span>
        </div>
      </div>

      {sections.map((s, i) => (
        <BriefSectionView key={s.id} section={s} num={numbers[i]} brief={brief} />
      ))}

      {references.length > 0 && (
        <section className="brief-footnotes">
          <h2 className="brief-footnotes-title">Footnotes</h2>
          <div className="brief-footnotes-sub">
            All {references.length} cited sources, compiled across sections
          </div>
          <div className="brief-footnotes-list">
            {references.map((r) => (
              <div className="brief-footnote-row" key={r.n}>
                <span className="brief-footnote-n">{r.n}.</span>
                <span className="brief-footnote-text">
                  {r.title}
                  {r.page ? ` (p. ${r.page})` : ''}.{' '}
                  <span className="brief-footnote-section">{r.section}</span>
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};
