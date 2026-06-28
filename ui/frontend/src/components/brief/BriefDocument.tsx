import React, { useEffect, useMemo, useRef, useState } from 'react';
import { SearchResult, SourceReference } from '../../types/api';
import { CitedMarkdown, CitedReferences } from '../citations/CitedContent';
import { buildGlobalCitations, SectionDisplay } from './briefCitations';
import { IconDownload, IconEdit, IconGrip, IconPlus, IconRefresh, IconSparkle } from './BriefIcons';
import { BriefSection } from './briefTypes';
import { UseBriefReturn } from './useBrief';

const tagClass = (tag: string): string => `brief-tag brief-tag-${tag.toLowerCase()}`;

interface SectionDnd {
  draggingId: string | null;
  dragOverId: string | null;
  onDragStart: (id: string) => void;
  onDragOver: (id: string) => void;
  onDrop: (id: string) => void;
  onDragEnd: () => void;
}

interface SectionViewProps {
  section: BriefSection;
  num: string;
  hasSiblings: boolean;
  dnd: SectionDnd;
  brief: UseBriefReturn;
  onSourceClick: (source: SourceReference) => void;
  // Globally-renumbered content + sources for the done view (see buildGlobalCitations).
  display?: SectionDisplay;
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

const BriefSectionView: React.FC<SectionViewProps> = ({
  section,
  num,
  hasSiblings,
  dnd,
  brief,
  onSourceClick,
  display,
}) => {
  const [editing, setEditing] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);
  const panelOpen = brief.regenFor === section.id;
  const anyResearching = brief.sections.some((s) => s.status === 'researching');
  const isDone = section.status === 'done';
  // Structural edits (reorder/add/remove) are locked while a research pass runs.
  const canEditStructure = !anyResearching;
  const draggable = canEditStructure && hasSiblings;
  const isDragging = dnd.draggingId === section.id;
  const isDragOver =
    !!dnd.draggingId && dnd.dragOverId === section.id && dnd.draggingId !== section.id;
  // View/evidence use the globally-renumbered content; editing uses the raw text.
  const viewContent = display?.content ?? section.content;
  const viewSources = display?.sources ?? section.sources;

  const sectionClass =
    `brief-doc-section${section.level === 2 ? ' brief-doc-section-sub' : ''}` +
    `${isDragging ? ' brief-doc-section-dragging' : ''}` +
    `${isDragOver ? ' brief-doc-section-dragover' : ''}`;

  return (
    <section
      ref={sectionRef}
      className={sectionClass}
      onDragOver={
        canEditStructure
          ? (e) => {
              e.preventDefault();
              dnd.onDragOver(section.id);
            }
          : undefined
      }
      onDrop={
        canEditStructure
          ? (e) => {
              e.preventDefault();
              dnd.onDrop(section.id);
            }
          : undefined
      }
    >
      <div className="brief-doc-section-head">
        {draggable && (
          <span
            className="brief-drag-handle"
            draggable
            title="Drag to reorder"
            aria-label="Drag to reorder heading"
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'move';
              if (sectionRef.current) e.dataTransfer.setDragImage(sectionRef.current, 16, 16);
              dnd.onDragStart(section.id);
            }}
            onDragEnd={dnd.onDragEnd}
          >
            <IconGrip />
          </span>
        )}
        {num && <span className="brief-doc-section-num">{num}</span>}
        <input
          className="brief-doc-section-title"
          value={section.title}
          onChange={(e) => brief.editTitle(section.id, e.target.value)}
          onBlur={brief.commitEdits}
        />
        {isDone && (
          <>
            <button className="brief-regen-btn" onClick={() => setEditing((v) => !v)}>
              <IconEdit /> {editing ? 'Done' : 'Edit text'}
            </button>
            <button className="brief-regen-btn" onClick={() => brief.openRegen(section.id)}>
              <IconRefresh /> Regenerate
            </button>
          </>
        )}
        {canEditStructure && (
          <span className="brief-section-struct">
            {section.level === 1 && (
              <button
                className="brief-section-act"
                title="Add a sub-heading under this heading"
                onClick={() => brief.addSubHeading(section.id)}
              >
                <IconPlus /> Sub-heading
              </button>
            )}
            <button
              className="brief-section-del"
              title="Delete this heading"
              aria-label="Delete this heading"
              onClick={() => brief.removeSection(section.id)}
            >
              ×
            </button>
          </span>
        )}
      </div>

      {panelOpen && <GuidancePanel section={section} brief={brief} />}

      {section.status === 'pending' && !panelOpen && !anyResearching && (
        <div className="brief-pending">
          <button
            className="brief-btn brief-btn-secondary brief-research-one-btn"
            onClick={() => brief.openRegen(section.id)}
            disabled={section.sample}
            title={section.sample ? 'Edit this heading before researching it' : undefined}
          >
            <IconSparkle /> Research this section
          </button>
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
                content={viewContent}
                sources={viewSources}
                onSourceClick={onSourceClick}
              />
            </div>
          )}
          <CitedReferences
            content={viewContent}
            sources={viewSources}
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
  onExportWord?: () => void;
  onExportMarkdown?: () => void;
  exportBusy?: boolean;
}

// Compact on/off switch for heading numbers, shown to the right of the title.
const NumberHeadingsToggle: React.FC<{ brief: UseBriefReturn }> = ({ brief }) => (
  <button
    type="button"
    className="brief-num-toggle-inline"
    role="switch"
    aria-checked={brief.numberHeadings}
    onClick={() => brief.setNumberHeadings(!brief.numberHeadings)}
    title="Show numbering before each heading"
  >
    <span className={`brief-switch${brief.numberHeadings ? ' brief-switch-on' : ''}`}>
      <span className="brief-switch-thumb" />
    </span>
    Number headings
  </button>
);

const autoSizeTitle = (el: HTMLTextAreaElement | null) => {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
};

export const BriefDocument: React.FC<BriefDocumentProps> = ({
  brief,
  onResultClick,
  onExportWord,
  onExportMarkdown,
  exportBusy,
}) => {
  const { sections, numbers } = brief;
  const [logOpen, setLogOpen] = useState(false);
  const titleRef = useRef<HTMLTextAreaElement>(null);
  const hasOutlineLog = brief.generatingActivity.length > 0;
  const { refs: references, display } = useMemo(() => buildGlobalCitations(sections), [sections]);

  // Drag-and-drop reordering state (which heading is being dragged / hovered).
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  useEffect(() => autoSizeTitle(titleRef.current), [brief.briefTitle]);

  const parentIdxOf = (i: number): number => {
    for (let k = i - 1; k >= 0; k--) {
      if (sections[k].level === 1) return k;
    }
    return -1;
  };

  // Show a drag handle only when the heading has at least one sibling to swap
  // with: another top-level heading, or another sub-heading under the same parent.
  const hasSiblings = (i: number): boolean => {
    const s = sections[i];
    if (s.level === 1) return sections.filter((x) => x.level === 1).length > 1;
    const pi = parentIdxOf(i);
    let count = 0;
    sections.forEach((x, k) => {
      if (x.level === 2 && parentIdxOf(k) === pi) count += 1;
    });
    return count > 1;
  };

  const handleDrop = (targetId: string) => {
    if (draggingId && draggingId !== targetId) brief.reorderSiblings(draggingId, targetId);
    setDraggingId(null);
    setDragOverId(null);
  };

  const dnd = {
    draggingId,
    dragOverId,
    onDragStart: setDraggingId,
    onDragOver: setDragOverId,
    onDrop: handleDrop,
    onDragEnd: () => {
      setDraggingId(null);
      setDragOverId(null);
    },
  };

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
        <div className="brief-doc-header-top">
          <div className="brief-eyebrow">EVIDENCE BRIEF</div>
          <div className="brief-doc-export-actions">
            {onExportMarkdown && (
              <button
                className="brief-export-md"
                onClick={onExportMarkdown}
                disabled={!sections.length}
                title="Download this brief as Markdown"
              >
                <IconDownload /> .md
              </button>
            )}
            {onExportWord && (
              <button
                className="brief-export-word"
                onClick={onExportWord}
                disabled={!sections.length || exportBusy}
                title="Export this brief to Word, with citations linked to the source documents"
              >
                {exportBusy ? 'Exporting…' : <><IconDownload /> Export to Word</>}
              </button>
            )}
          </div>
        </div>
        <div className="brief-doc-title-row">
          <textarea
            ref={titleRef}
            className="brief-doc-title-input"
            value={brief.briefTitle}
            onChange={(e) => {
              brief.setBriefTitle(e.target.value);
              autoSizeTitle(e.target);
            }}
            onBlur={brief.commitEdits}
            rows={1}
            aria-label="Brief title"
          />
          <NumberHeadingsToggle brief={brief} />
        </div>
        <div className="brief-doc-meta">
          <span>{sections.length} sections</span>
          <span>·</span>
          <span>{brief.totalSources} sources synthesised</span>
          {hasOutlineLog && (
            <>
              <span>·</span>
              <button
                className="brief-meta-link"
                onClick={() => setLogOpen((v) => !v)}
                aria-expanded={logOpen}
              >
                Outline analysis
              </button>
            </>
          )}
          {sections.length > 0 && (
            <span className="brief-edit-hint">
              <span className="brief-icon">✎</span> Click on titles to edit research topics
            </span>
          )}
        </div>
        {brief.stage === 'research' && (
          <div className="brief-doc-progress">
            <div className="brief-doc-progress-row">
              <span>Researching…</span>
              <span>
                {brief.doneCount}/{sections.length}
              </span>
            </div>
            <div className="brief-progress-track">
              <div className="brief-progress-fill" style={{ width: `${brief.totalProgress}%` }} />
            </div>
          </div>
        )}
        {logOpen && hasOutlineLog && (
          <div className="brief-outline-log">
            <div className="brief-outline-log-head">
              Outline research — queries run and sources read
            </div>
            <div className="brief-activity">
              {brief.generatingActivity.map((ev, i) => (
                <div className="brief-activity-row" key={`${ev.tag}-${i}`}>
                  <span className={tagClass(ev.tag)}>{ev.tag}</span>
                  <span>{ev.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {sections.map((s, i) => (
        <BriefSectionView
          key={s.id}
          section={s}
          num={brief.numberHeadings ? numbers[i] : ''}
          hasSiblings={hasSiblings(i)}
          dnd={dnd}
          brief={brief}
          onSourceClick={handleSourceClick}
          display={display.get(s.id)}
        />
      ))}

      <div className="brief-doc-actions">
        <button className="brief-add-heading" onClick={brief.addHeading}>
          <IconPlus /> Add heading
        </button>
        {brief.stage === 'outline' && (
          <button
            className="brief-btn brief-btn-primary"
            onClick={brief.startResearch}
            disabled={!sections.length}
          >
            Start deep research →
          </button>
        )}
      </div>

      {references.length > 0 && (
        <section className="brief-footnotes">
          <h2 className="brief-footnotes-title">References</h2>
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
                    {r.page ? `, p.${r.page}` : ''}
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
