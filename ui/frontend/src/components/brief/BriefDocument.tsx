import React, { useEffect, useMemo, useRef, useState } from 'react';
import { SearchResult, SourceReference } from '../../types/api';
import { CitedMarkdown, CitedReferences } from '../citations/CitedContent';
import { buildGlobalCitations, SectionDisplay } from './briefCitations';
import {
  IconClock,
  IconCopy,
  IconDownload,
  IconEdit,
  IconRefresh,
  IconShare,
  IconSparkle,
} from './BriefIcons';
import { BriefToc } from './BriefToc';
import { BriefSection, SectionAuditEntry } from './briefTypes';
import { UseBriefReturn } from './useBrief';
import { BriefDiff } from './BriefDiff';
import { BriefSectionAudit } from './BriefSectionAudit';

const tagClass = (tag: string): string => `brief-tag brief-tag-${tag.toLowerCase()}`;

// The changes view for one audit entry: a diff header (Hide, plus Keep/Reject
// for the still-pending change) over the rendered before→after diff.
const SectionChangesView: React.FC<{
  entry: SectionAuditEntry;
  viewingPending: boolean;
  onHide: () => void;
  onKeep: () => void;
  onReject: () => void;
}> = ({ entry, viewingPending, onHide, onKeep, onReject }) => (
  <div className="brief-doc-content">
    <div className="brief-diff-head">
      <span>
        Changes from the {entry.kind === 'update' ? 'update' : 'edit'}
        {viewingPending ? '' : ` on ${new Date(entry.at).toLocaleDateString()}`}
      </span>
      <span className="brief-diff-actions">
        <button className="brief-diff-dismiss brief-diff-hide" onClick={onHide} title="Hide the diff">
          Hide changes
        </button>
        {viewingPending && (
          <>
            <button className="brief-diff-dismiss brief-diff-keep" onClick={onKeep}>
              Keep Edits
            </button>
            <button className="brief-diff-dismiss brief-diff-reject" onClick={onReject}>
              Reject Edits
            </button>
          </>
        )}
      </span>
    </div>
    <BriefDiff oldText={entry.before || ''} newText={entry.after || ''} />
  </div>
);

// The Edit/Update instruction panel (keeps the current text; runs a revise).
const AiInstructionPanel: React.FC<{
  mode: 'edit' | 'update';
  title: string;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}> = ({ mode, title, value, onChange, onSubmit, onCancel }) => (
  <div className="brief-regen-panel brief-ai-panel">
    <div className="brief-regen-title">
      {mode === 'edit' ? `Edit “${title}”` : `Update “${title}”`}
    </div>
    <div className="brief-ai-panel-hint">
      {mode === 'edit'
        ? 'Keeps the current text and revises it to your instruction (does not replace it unless you ask).'
        : 'Searches the library for sources published since this section was last run and folds any new findings in. Add an optional focus below.'}
    </div>
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      rows={2}
      placeholder={
        mode === 'edit'
          ? 'e.g. “Adjust so the viewpoint relates more to domestic policy”'
          : 'Optional focus for the update — e.g. “prioritise enforcement actions”'
      }
    />
    <div className="brief-regen-actions">
      <button
        className="brief-btn brief-btn-primary"
        onClick={onSubmit}
        disabled={mode === 'edit' && !value.trim()}
      >
        {mode === 'edit' ? 'Apply edit' : 'Run update'}
      </button>
      <button className="brief-btn brief-btn-secondary" onClick={onCancel}>
        Cancel
      </button>
    </div>
  </div>
);

interface SectionViewProps {
  section: BriefSection;
  num: string;
  brief: UseBriefReturn;
  onSourceClick: (source: SourceReference) => void;
  // Globally-renumbered content + sources for the done view (see buildGlobalCitations).
  display?: SectionDisplay;
  // Viewer-only (shared brief): no editing or AI actions.
  readOnly?: boolean;
}

// A textarea for editing a section's heading guidance / regenerating, shown for
// both pending sections (research with guidance) and done sections (re-research).
const GuidancePanel: React.FC<{ section: BriefSection; brief: UseBriefReturn }> = ({
  section,
  brief,
}) => {
  const isPending = section.status === 'pending';
  const briefVoice = brief.voices.find((v) => v.id === brief.briefVoiceId) || null;
  const ownVoice = brief.voices.find((v) => v.id === section.voiceId) || null;
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
      {brief.voices.length > 0 && (
        <>
          <div className="brief-regen-voice-label">Voice &amp; tone profile</div>
          <select
            className="brief-regen-voice-select"
            value={section.voiceId || ''}
            onChange={(e) => brief.setSectionVoiceId(section.id, e.target.value || null)}
            aria-label="Voice and tone profile for this section"
          >
            <option value="">
              Use brief default{briefVoice ? ` — ${briefVoice.name}` : ''}
            </option>
            {brief.voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
          <div className="brief-regen-voice-hint">
            {ownVoice
              ? ownVoice.instructions.slice(0, 150)
              : briefVoice
                ? `Inherits the brief profile — ${briefVoice.instructions.slice(0, 120)}`
                : 'No voice profile applied'}
          </div>
        </>
      )}
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

// Content + sources for the done/stale views: the globally-renumbered display
// variant when available, else the section's own.
const sectionView = (section: BriefSection, display?: SectionDisplay) => ({
  content: display?.content ?? section.content,
  sources: display?.sources ?? section.sources,
});

// The AI action toolbar shown on a completed section.
const SectionTools: React.FC<{
  editing: boolean;
  auditCount: number;
  onToggleEdit: () => void;
  onRegenerate: () => void;
  onAiEdit: () => void;
  onAiUpdate: () => void;
  onOpenLog: () => void;
}> = ({ editing, auditCount, onToggleEdit, onRegenerate, onAiEdit, onAiUpdate, onOpenLog }) => (
  <div className="brief-doc-section-tools">
    <button className="brief-regen-btn" onClick={onToggleEdit}>
      <IconEdit /> {editing ? 'Done' : 'Manually Edit'}
    </button>
    <button className="brief-regen-btn" onClick={onRegenerate}>
      <IconRefresh /> AI Regenerate
    </button>
    <button
      className="brief-regen-btn"
      onClick={onAiEdit}
      title="Revise this section with an AI instruction, keeping the current content"
    >
      <IconSparkle /> AI Edit
    </button>
    <button
      className="brief-regen-btn"
      onClick={onAiUpdate}
      title="Search for sources published since this section was last run and fold them in"
    >
      <IconClock /> AI Get Updates
    </button>
    <button className="brief-section-log-link" onClick={onOpenLog}>
      Log{auditCount ? ` (${auditCount})` : ''}
    </button>
  </div>
);

// The "research this section" prompt shown for a pending section.
const SectionPending: React.FC<{ sample?: boolean; onResearch: () => void }> = ({
  sample,
  onResearch,
}) => (
  <div className="brief-pending">
    <button
      className="brief-btn brief-btn-secondary brief-research-one-btn"
      onClick={onResearch}
      disabled={sample}
      title={sample ? 'Edit this heading before researching it' : undefined}
    >
      <IconSparkle /> Research this section
    </button>
  </div>
);

// The live "researching…"/"revising…" panel; keeps the current text greyed out
// in place while a revise (Edit/Update) runs.
const SectionResearching: React.FC<{
  section: BriefSection;
  display?: SectionDisplay;
  onSourceClick: (source: SourceReference) => void;
}> = ({ section, display, onSourceClick }) => {
  const { content, sources } = sectionView(section, display);
  return (
    <>
      <div className="brief-researching">
        <div className="brief-researching-head">
          <span className="brief-spinner" />
          <span className="brief-researching-label">
            {section.revising ? 'Revising this section' : 'Researching this section'}
          </span>
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
      {section.revising && !!section.content && (
        // The current text stays in place, greyed out, until the revised version
        // arrives and swaps in atomically.
        <div className="brief-doc-content brief-doc-content-stale" aria-busy="true">
          <CitedMarkdown content={content} sources={sources} onSourceClick={onSourceClick} />
        </div>
      )}
    </>
  );
};

// The completed-section body: raw-edit textarea, a change diff, or the rendered
// content — plus the collapsible evidence list.
const SectionDoneBody: React.FC<{
  section: BriefSection;
  brief: UseBriefReturn;
  display?: SectionDisplay;
  editing: boolean;
  diffEntry: SectionAuditEntry | null;
  viewingPending: boolean;
  onSourceClick: (source: SourceReference) => void;
  onCloseDiff: () => void;
}> = ({
  section,
  brief,
  display,
  editing,
  diffEntry,
  viewingPending,
  onSourceClick,
  onCloseDiff,
}) => {
  const { content, sources } = sectionView(section, display);
  return (
    <>
      {editing ? (
        <textarea
          className="brief-edit-textarea"
          value={section.content}
          onChange={(e) => brief.editContent(section.id, e.target.value)}
          onBlur={brief.commitEdits}
          rows={Math.min(28, Math.max(8, section.content.split('\n').length + 2))}
        />
      ) : diffEntry && diffEntry.before != null ? (
        <SectionChangesView
          entry={diffEntry}
          viewingPending={viewingPending}
          onHide={onCloseDiff}
          onKeep={() => {
            onCloseDiff();
            brief.dismissChanges(section.id);
          }}
          onReject={() => {
            onCloseDiff();
            brief.rejectChanges(section.id);
          }}
        />
      ) : (
        <div className="brief-doc-content">
          <CitedMarkdown content={content} sources={sources} onSourceClick={onSourceClick} />
        </div>
      )}
      <CitedReferences
        content={content}
        sources={sources}
        onSourceClick={onSourceClick}
        collapsible
        labelPrefix="Evidence"
        className="brief-evidence"
      />
    </>
  );
};

const BriefSectionView: React.FC<SectionViewProps> = ({
  section,
  num,
  brief,
  onSourceClick,
  display,
  readOnly = false,
}) => {
  const [editing, setEditing] = useState(false);
  // AI Edit/Update instruction panel + audit modal + changes toggle.
  const [aiPanel, setAiPanel] = useState<null | 'edit' | 'update'>(null);
  const [aiText, setAiText] = useState('');
  const [logOpen, setLogOpen] = useState(false);
  // Which audit entry's diff is on screen (by id), or null. Any edit/update
  // entry with a stored before/after can be viewed — including on a reloaded
  // brief — not just the latest pending change.
  const [diffEntryId, setDiffEntryId] = useState<string | null>(null);
  const panelOpen = brief.regenFor === section.id;
  const isDone = section.status === 'done';
  const anyResearching = brief.sections.some((s) => s.status === 'researching');
  const audit = section.audit ?? [];
  const auditCount = audit.length;
  const hasChanges = !!section.prevContent;
  // The still-pending change (un-kept) is the latest audit entry; only it offers
  // Keep/Reject. Everything else is view-only.
  const pendingEntryId = hasChanges && audit.length ? audit[audit.length - 1].id : null;
  const diffEntry = diffEntryId ? audit.find((e) => e.id === diffEntryId) ?? null : null;
  const viewingPending = !!diffEntryId && diffEntryId === pendingEntryId;
  // Surface the pending diff automatically once an edit/update completes (a new
  // pending entry appears).
  useEffect(() => {
    if (pendingEntryId) setDiffEntryId(pendingEntryId);
  }, [pendingEntryId]);
  const submitAi = () => {
    const panel = aiPanel;
    if (!panel) return;
    setAiPanel(null);
    setDiffEntryId(null);
    brief.reviseSection(section.id, panel, aiText.trim() || null);
    setAiText('');
  };

  return (
    <section
      id={`brief-section-${section.id}`}
      className={`brief-doc-section${section.level === 2 ? ' brief-doc-section-sub' : ''}`}
    >
      <div className="brief-doc-section-head">
        {num && <span className="brief-doc-section-num">{num}</span>}
        <input
          className="brief-doc-section-title"
          value={section.title}
          onChange={(e) => brief.editTitle(section.id, e.target.value)}
          onBlur={brief.commitEdits}
          readOnly={readOnly}
        />
      </div>

      {isDone && !readOnly && (
        <SectionTools
          editing={editing}
          auditCount={auditCount}
          onToggleEdit={() => setEditing((v) => !v)}
          onRegenerate={() => brief.openRegen(section.id)}
          onAiEdit={() => {
            setAiText('');
            setAiPanel((p) => (p === 'edit' ? null : 'edit'));
          }}
          onAiUpdate={() => {
            setAiText('');
            setAiPanel((p) => (p === 'update' ? null : 'update'));
          }}
          onOpenLog={() => setLogOpen(true)}
        />
      )}

      {aiPanel && (
        <AiInstructionPanel
          mode={aiPanel}
          title={section.title}
          value={aiText}
          onChange={setAiText}
          onSubmit={submitAi}
          onCancel={() => {
            setAiPanel(null);
            setAiText('');
          }}
        />
      )}

      {logOpen && (
        <BriefSectionAudit
          title={section.title}
          audit={audit}
          pendingEntryId={pendingEntryId}
          // Any edit/update entry with a stored before/after can be re-viewed —
          // clicking its row opens that change's diff.
          onShowChanges={(entryId) => {
            setLogOpen(false);
            setDiffEntryId(entryId);
          }}
          onClose={() => setLogOpen(false)}
        />
      )}

      {panelOpen && <GuidancePanel section={section} brief={brief} />}

      {section.status === 'pending' && !panelOpen && !anyResearching && !readOnly && (
        <SectionPending sample={section.sample} onResearch={() => brief.openRegen(section.id)} />
      )}

      {section.status === 'researching' && (
        <SectionResearching section={section} display={display} onSourceClick={onSourceClick} />
      )}

      {isDone && (
        <SectionDoneBody
          section={section}
          brief={brief}
          display={display}
          editing={editing}
          diffEntry={diffEntry}
          viewingPending={viewingPending}
          onSourceClick={onSourceClick}
          onCloseDiff={() => setDiffEntryId(null)}
        />
      )}
    </section>
  );
};

// The dropdown behind "Export to Word": references-list vs footnotes style.
const ExportMenu: React.FC<{
  disabled: boolean;
  busy: boolean;
  open: boolean;
  setOpen: (fn: (open: boolean) => boolean) => void;
  onExportWord: (style: 'links' | 'footnotes') => void;
}> = ({ disabled, busy, open, setOpen, onExportWord }) => (
  <div className="dropdown-container brief-export-menu">
    <button
      className="brief-export-word"
      onClick={() => setOpen((o) => !o)}
      onBlur={() => setTimeout(() => setOpen(() => false), 200)}
      disabled={disabled || busy}
      aria-haspopup="menu"
      aria-expanded={open}
      title="Export this brief to Word, with citations linked to the source documents"
    >
      {busy ? 'Exporting…' : <><IconDownload /> Export to Word ▾</>}
    </button>
    {open && !busy && (
      <div className="brief-export-dropdown" role="menu">
        <button
          className="brief-export-option"
          role="menuitem"
          onClick={() => { setOpen(() => false); onExportWord('links'); }}
        >
          References list
          <span className="brief-export-option-hint">Inline [n] citations + reference excerpts</span>
        </button>
        <button
          className="brief-export-option"
          role="menuitem"
          onClick={() => { setOpen(() => false); onExportWord('footnotes'); }}
        >
          Footnotes on page
          <span className="brief-export-option-hint">Each citation as a footnote on the relevant page</span>
        </button>
      </div>
    )}
  </div>
);

// The document-level action row: regenerate/update all, share, save-as-template
// and the Word export menu. Owner-only actions are hidden for viewers.
const HeaderActions: React.FC<{
  brief: UseBriefReturn;
  readOnly: boolean;
  canEditStructure: boolean;
  onOpenShare?: () => void;
  onSaveTemplate?: () => void;
  onExportWord?: (style: 'links' | 'footnotes') => void;
  exportBusy?: boolean;
  exportMenuOpen: boolean;
  setExportMenuOpen: React.Dispatch<React.SetStateAction<boolean>>;
}> = ({
  brief,
  readOnly,
  canEditStructure,
  onOpenShare,
  onSaveTemplate,
  onExportWord,
  exportBusy,
  exportMenuOpen,
  setExportMenuOpen,
}) => {
  const { sections } = brief;
  const hasSections = sections.length > 0;
  return (
    <div className="brief-doc-header-actions">
      {!readOnly && hasSections && (
        <button
          className="brief-regen-all"
          onClick={brief.startResearch}
          disabled={!canEditStructure}
          title="Re-research every section from scratch"
        >
          <IconRefresh /> AI Regenerate All
        </button>
      )}
      {!readOnly && sections.some((s) => s.status === 'done') && (
        <button
          className="brief-regen-all"
          onClick={brief.updateAll}
          disabled={!canEditStructure}
          title="Fold sources published since each section was last run into every section"
        >
          <IconClock /> AI Get All Recent Updates
        </button>
      )}
      {!readOnly && onOpenShare && (
        <button
          className="brief-regen-all"
          onClick={onOpenShare}
          title="Share this brief (viewer-only) with people or groups"
        >
          <IconShare /> Share
        </button>
      )}
      {!readOnly && onSaveTemplate && hasSections && (
        <button
          className="brief-regen-all"
          onClick={onSaveTemplate}
          title="Save this brief's headings as a reusable template"
        >
          <IconCopy /> Save as Template
        </button>
      )}
      {onExportWord && (
        <ExportMenu
          disabled={!hasSections}
          busy={!!exportBusy}
          open={exportMenuOpen}
          setOpen={setExportMenuOpen}
          onExportWord={onExportWord}
        />
      )}
    </div>
  );
};

interface BriefDocumentProps {
  brief: UseBriefReturn;
  onResultClick?: (result: SearchResult) => void;
  // Export the brief to Word. 'links' keeps inline [n] citations; 'footnotes'
  // renders each citation as a Word footnote on the relevant page.
  onExportWord?: (style: 'links' | 'footnotes') => void;
  exportBusy?: boolean;
  // Brief Central integrations (remote mode only).
  onOpenShare?: () => void;
  onSaveTemplate?: () => void;
}

const autoSizeTitle = (el: HTMLTextAreaElement | null) => {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
};

export const BriefDocument: React.FC<BriefDocumentProps> = ({
  brief,
  onResultClick,
  onExportWord,
  exportBusy,
  onOpenShare,
  onSaveTemplate,
}) => {
  const { sections, numbers } = brief;
  const [logOpen, setLogOpen] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const titleRef = useRef<HTMLTextAreaElement>(null);
  const hasOutlineLog = brief.generatingActivity.length > 0;
  const { refs: references, display } = useMemo(() => buildGlobalCitations(sections), [sections]);

  useEffect(() => autoSizeTitle(titleRef.current), [brief.briefTitle]);

  // Viewer-only: a brief shared with (not owned by) this user renders read-only.
  const readOnly = !brief.canEdit;
  // Structural edits (reorder/add/remove via the TOC) lock while research runs.
  const canEditStructure = !readOnly && !sections.some((s) => s.status === 'researching');

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
          <HeaderActions
            brief={brief}
            readOnly={readOnly}
            canEditStructure={canEditStructure}
            onOpenShare={onOpenShare}
            onSaveTemplate={onSaveTemplate}
            onExportWord={onExportWord}
            exportBusy={exportBusy}
            exportMenuOpen={exportMenuOpen}
            setExportMenuOpen={setExportMenuOpen}
          />
        </div>
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
          readOnly={readOnly}
        />
        <div className="brief-doc-meta">
          <span>{sections.length} sections</span>
          <span>·</span>
          <span>{brief.totalSources} sources synthesised</span>
          {readOnly && brief.ownerName && (
            <>
              <span>·</span>
              <span className="brief-viewer-chip">Shared by {brief.ownerName} — view only</span>
            </>
          )}
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
          {!readOnly && sections.length > 0 && (
            <span className="brief-edit-hint">
              <span className="brief-icon">✎</span> Click on titles to edit research topics
            </span>
          )}
        </div>
        {brief.stage === 'research' && (
          <div className="brief-doc-progress">
            <div className="brief-doc-progress-row">
              <span>Researching…</span>
              <span className="brief-doc-progress-right">
                {brief.doneCount}/{sections.length}
                <button
                  className="brief-stop-btn"
                  onClick={brief.stopResearch}
                  title="Stop all research"
                >
                  ■ Stop
                </button>
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
              <span>Outline research — queries run and sources read</span>
              <button
                className="brief-outline-log-close"
                onClick={() => setLogOpen(false)}
                title="Close"
                aria-label="Close outline analysis"
              >
                ×
              </button>
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

      {sections.length > 0 && <BriefToc brief={brief} canEdit={canEditStructure} />}

      {sections.map((s, i) => (
        <BriefSectionView
          key={s.id}
          section={s}
          num={brief.numberHeadings ? numbers[i] : ''}
          brief={brief}
          onSourceClick={handleSourceClick}
          display={display.get(s.id)}
          readOnly={readOnly}
        />
      ))}

      {brief.stage === 'outline' && !readOnly && (
        <div className="brief-doc-actions">
          <button
            className="brief-btn brief-btn-primary"
            onClick={brief.startResearch}
            disabled={!sections.length}
          >
            Start deep research →
          </button>
        </div>
      )}

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
