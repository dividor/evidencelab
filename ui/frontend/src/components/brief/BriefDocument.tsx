import React, { useEffect, useRef, useState } from 'react';
import { SearchResult, SourceReference } from '../../types/api';
import { CitedMarkdown, CitedReferences, RequestCitationHighlight } from '../citations/CitedContent';
import { IconClock, IconCopy, IconDownload, IconEdit, IconFactCheck, IconRefresh, IconShare, IconSparkle } from './BriefIcons';
import { BriefActionMenu, BriefAction } from './BriefActionMenu';
import { BriefDocumentActions, DocumentAiActions, useDocumentActionLayout } from './BriefDocumentActions';
import { BriefAskAi } from './BriefAskAi';
import { BriefSectionFrame } from './BriefSectionFrame';
import { BriefClaimDialog } from './BriefClaimDialog';
import { useFactMarkPainter, UseBriefFactCheckReturn } from './useBriefFactCheck';
import type { BriefFactCheckEvidence, BriefFactCheckMark } from '../../types/testing';
import { BriefLengthControl } from './BriefLengthControl';
import { countWords, describeTarget } from './briefLength';
import { BriefReferences } from './BriefReferences';
import { BriefToc } from './BriefToc';
import { BriefSelection } from './BriefSelectionMenu';
import { BUBBLE_CLASS, CommentMark, MARK_CLASS, paintCommentMarks } from './briefCommentMarks';
import {
  BriefSection,
  PROMPT_MAX_CHARS,
  SectionAuditEntry,
  SectionRunDetail,
  UnresolvedMarker,
} from './briefTypes';
import { BriefVoiceSelect, briefDefaultSuffix, voiceHint } from './BriefVoiceSelect';
import { UseBriefReturn } from './useBrief';
import { BriefDiff } from './BriefDiff';
import { BriefSectionAudit } from './BriefSectionAudit';
import { ReviewBar, SectionVersionView, useSectionChanges } from './BriefSectionChanges';
import { BriefRunOriginal } from './BriefRunOriginal';
import { BriefVersionsModal } from './BriefVersionsModal';
import { AutoGrowTextarea } from '../AutoGrowTextarea';

const tagClass = (tag: string): string => `brief-tag brief-tag-${tag.toLowerCase()}`;

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
    <AutoGrowTextarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      maxLength={PROMPT_MAX_CHARS}
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
  // Viewer-only (shared brief): no editing or AI actions.
  readOnly?: boolean;
  checkingFacts?: boolean;
  // Hover on an un-enriched citation asks for that source to be highlighted.
  onRequestHighlight?: RequestCitationHighlight;
  // Commented passages in this section, and the thread currently open.
  marks?: CommentMark[];
  onOpenThread?: (threadId: string) => void;
  activeThreadId?: string | null;
  // Fact Checker: the flagged passages of this section to highlight, the
  // note shown when the check no longer covers this section, and the pointer
  // moving over the marks (the document shows the judge's explanation).
  factMarks?: BriefFactCheckMark[];
  factNote?: string;
  onSelectClaim?: (target: EventTarget | null) => void;
}

// Tooltip for a section's word count: which target (if any) it was written to.
const sectionWordsTitle = (section: BriefSection, briefTarget: number | null): string => {
  const target = section.targetWords ?? briefTarget;
  return target ? `Target: about ${target} words` : 'No length target';
};

const UNMATCHED_FLASH_MS = 1600;

// Citations of the section the API could not match to a source: the agent
// cited a number it never returned, or returned a record without a chunk id.
// The text shows each as a red number badge (UnmatchedCitation); this header
// names them, and clicking one scrolls to it in the section, stepping through
// its uses on each click.
export const UnresolvedCitationsWarning: React.FC<{
  unresolved?: UnresolvedMarker[];
  // The section has a log (Section History) holding the run's original output.
  canOpenLog?: boolean;
  onOpenLog?: () => void;
}> = ({ unresolved, canOpenLog, onOpenLog }) => {
  const ref = useRef<HTMLDivElement>(null);
  const visits = useRef<Map<number, number>>(new Map());
  if (!unresolved || !unresolved.length) return null;
  const noChunk = unresolved.some((u) => u.reason === 'no-chunk-id');
  const jumpTo = (n: number) => {
    const section = ref.current?.closest('.brief-doc-section');
    const marks = Array.from(
      section?.querySelectorAll<HTMLElement>(`.citation-unmatched[data-unmatched="${n}"]`) ?? [],
    );
    if (!marks.length) return;
    const visit = visits.current.get(n) ?? 0;
    const mark = marks[visit % marks.length];
    visits.current.set(n, visit + 1);
    mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    mark.classList.add('citation-unmatched-flash');
    window.setTimeout(() => mark.classList.remove('citation-unmatched-flash'), UNMATCHED_FLASH_MS);
  };
  return (
    <div className="brief-unmatched-warning" role="status" ref={ref}>
      <span className="brief-unmatched-title">
        {unresolved.length === 1 ? '1 citation has' : `${unresolved.length} citations have`} no source
      </span>
      {unresolved.map((u) => (
        <button
          key={u.n}
          type="button"
          className="citation-unmatched citation-unmatched-chip"
          onClick={() => jumpTo(u.n)}
          title={`Show where citation ${u.n} has no source`}
          aria-label={`Show where citation ${u.n} has no source`}
        >
          {u.n}
        </button>
      ))}
      <span className="brief-unmatched-detail">
        The research agent cited {unresolved.length === 1 ? 'a number' : 'numbers'} it was never
        given{noChunk ? ', or a source with no chunk id' : ''}.{' '}
        {canOpenLog && onOpenLog ? (
          <button type="button" className="brief-unmatched-log" onClick={onOpenLog}>
            See its original output
          </button>
        ) : (
          'Section History has its original output.'
        )}
      </span>
    </div>
  );
};

// An introduction (a top-level heading with sub-headings) that kept headings of
// its own after its re-runs; see briefIntro.ts.
export const IntroHeadingWarning: React.FC<{ headings?: number }> = ({ headings }) =>
  headings ? (
    <div className="brief-section-warning" role="status">
      This introduction still has {headings} heading{headings === 1 ? '' : 's'} of its own after
      re-running. An introduction should frame its sub-sections without headings: edit them out, or
      choose Regenerate under Ask AI.
    </div>
  ) : null;

// A textarea for editing a section's heading guidance / regenerating, shown for
// both pending sections (research with guidance) and done sections (re-research).

const GuidancePanel: React.FC<{
  section: BriefSection;
  brief: UseBriefReturn;
  // The inline panel for an un-researched section has nothing to cancel back to.
  hideCancel?: boolean;
}> = ({ section, brief, hideCancel }) => {
  const isPending = section.status === 'pending';
  const briefVoice = brief.voices.find((v) => v.id === brief.briefVoiceId) || null;
  const ownVoice = brief.voices.find((v) => v.id === section.voiceId) || null;
  const showVoice = brief.voices.length > 0 || !!section.voiceId || !!brief.briefVoiceId;
  return (
    <div className="brief-regen-panel">
      <div className="brief-regen-title">
        {isPending ? 'Research' : 'Regenerate'} “{section.title}”
      </div>
      <AutoGrowTextarea
        value={section.guidance || ''}
        onChange={(e) => brief.setSectionGuidance(section.id, e.target.value)}
        maxLength={PROMPT_MAX_CHARS}
        rows={2}
        placeholder="Optional: add focus or guidance — e.g. ‘emphasise sub-Saharan Africa & 2020 onward’"
      />
      {showVoice && (
        <>
          <div className="brief-regen-voice-label">Voice &amp; tone profile</div>
          <BriefVoiceSelect
            className="brief-regen-voice-select"
            value={section.voiceId}
            voices={brief.voices}
            onChange={(id) => brief.setSectionVoiceId(section.id, id)}
            emptyLabel={`Use brief default${briefDefaultSuffix(brief.briefVoiceId, briefVoice)}`}
            ariaLabel="Voice and tone profile for this section"
          />
          <div className="brief-regen-voice-hint">
            {voiceHint(section.voiceId, ownVoice, brief.briefVoiceId, briefVoice)}
          </div>
        </>
      )}
      <div className="brief-regen-voice-label">Section length</div>
      <BriefLengthControl
        value={section.targetWords}
        onChange={(target) => brief.setSectionTargetWords(section.id, target)}
        inheritLabel={`Use brief target — ${describeTarget(brief.targetWords)}`}
        ariaLabel="Length target for this section"
      />
      <div className="brief-regen-actions">
        <button
          className="brief-btn brief-btn-primary"
          onClick={(event) => {
            event.currentTarget.closest('section')?.querySelector<HTMLInputElement>('.brief-doc-section-title')?.focus({ preventScroll: true });
            brief.regenerate(section.id, (section.guidance || '').trim() || null);
          }}
        >
          {isPending ? 'Research section' : 'Re-research section'}
        </button>
        {!hideCancel && (
          <button className="brief-btn brief-btn-secondary" onClick={brief.closeRegen}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
};

// The action toolbar shown on a completed section.
const SectionTools: React.FC<{
  title: string;
  editing: boolean;
  auditCount: number;
  showLog: boolean;
  onToggleEdit: () => void;
  onRegenerate: () => void;
  checkingFacts: boolean;
  regenerationFailed: boolean;
  onAiEdit: () => void;
  onAiUpdate: () => void;
  onOpenLog: () => void;
}> = ({
  title,
  editing,
  auditCount,
  showLog,
  onToggleEdit,
  onRegenerate,
  checkingFacts,
  regenerationFailed,
  onAiEdit,
  onAiUpdate,
  onOpenLog,
}) => (
  <div className="brief-doc-section-tools">
    <BriefAskAi
      label={`Ask AI for ${title}`} disabled={checkingFacts}
      buttonClass="brief-regen-btn"
      actions={[
        {
          label: regenerationFailed ? 'AI Research Settings' : 'AI Regenerate',
          icon: IconRefresh,
          onSelect: onRegenerate,
        },
        {
          label: 'AI Edit',
          icon: IconEdit,
          onSelect: onAiEdit,
          title: 'Revise this section with an AI instruction, keeping the current content',
        },
        {
          label: 'AI Get Updates',
          icon: IconClock,
          onSelect: onAiUpdate,
          title: 'Search for sources published since this section was last run and fold them in',
        },
      ]}
    />
    <button className="brief-regen-btn" onClick={onToggleEdit} disabled={checkingFacts}>
      <IconEdit /> {editing ? 'Done' : 'Edit'}
    </button>
    {showLog && (
      <BriefActionMenu label={`More actions for ${title}`} buttonText="More Actions" buttonClass="brief-regen-btn brief-section-more"
        actions={[{ label: 'Section History' + (auditCount ? ' (' + auditCount + ')' : ''), icon: IconClock, onSelect: onOpenLog }]} />
    )}
  </div>
);

// A signed-in viewer's way into the section Log (the owner's is in the
// section tools).
const ViewerLogButton: React.FC<{ show: boolean; auditCount: number; onOpen: () => void }> = ({
  show,
  auditCount,
  onOpen,
}) => {
  if (!show) return null;
  return (
    <div className="brief-doc-section-tools">
      <button className="brief-section-log-link" onClick={onOpen}>
        Section History{auditCount ? ` (${auditCount})` : ''}
      </button>
    </div>
  );
};

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
  onSourceClick: (source: SourceReference) => void;
}> = ({ section, onSourceClick }) => {
  const { content, sources } = section;
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
  editing: boolean;
  readOnly: boolean;
  // A Log row opened to view that version, or null.
  versionEntry: SectionAuditEntry | null;
  onCloseVersion: () => void;
  // Whether a change awaiting review has its review open (made while the
  // brief is open, or chosen from the Section History), and whether it is
  // shown as tracked changes.
  reviewOpen: boolean;
  showingChanges: boolean;
  onToggleChanges: () => void;
  onSourceClick: (source: SourceReference) => void;
  onRequestHighlight?: RequestCitationHighlight;
  marks?: CommentMark[];
  onOpenThread?: (threadId: string) => void;
  activeThreadId?: string | null;
  factMarks?: BriefFactCheckMark[];
  factNote?: string;
  onSelectClaim?: (target: EventTarget | null) => void;
}> = ({
  section,
  brief,
  editing,
  readOnly,
  versionEntry,
  onCloseVersion,
  reviewOpen,
  showingChanges,
  onToggleChanges,
  onSourceClick,
  onRequestHighlight,
  marks,
  onOpenThread,
  activeThreadId,
  factMarks,
  factNote,
  onSelectClaim,
}) => {
  // Rendered exactly as the API returned them: the renumbered text and the
  // display sources behind its numbers.
  const { content, sources } = section;
  // Only the owner can keep or reject, once the review is open; otherwise the
  // section shows the text as it stands.
  const review = readOnly || !reviewOpen ? null : (section.pendingReview ?? null);
  const proseRef = useRef<HTMLDivElement>(null);

  // Paint commented passages after the markdown renders. The marks live in the
  // DOM rather than in React's tree, so a re-render of the prose wipes them —
  // an observer puts them back. It is disconnected while painting so our own
  // mutations cannot trigger another pass.
  useEffect(() => {
    const el = proseRef.current;
    if (!el) return;
    const options = { childList: true, subtree: true, characterData: true };
    const observer = new MutationObserver(() => {
      if (!el.querySelector(`.${MARK_CLASS}`) && (marks || []).length) repaint();
    });
    function repaint(): void {
      observer.disconnect();
      paintCommentMarks(el as HTMLElement, marks || []);
      observer.observe(el as HTMLElement, options);
    }
    repaint();
    return () => observer.disconnect();
  }, [content, marks]);

  // The Fact Checker's flagged passages, painted the same way.
  useFactMarkPainter(proseRef, content, factMarks);

  // Show which passage the open thread belongs to.
  useEffect(() => {
    const el = proseRef.current;
    if (!el) return;
    el.querySelectorAll(`.${MARK_CLASS}`).forEach((m) => {
      m.classList.toggle(
        'brief-comment-mark-active',
        !!activeThreadId && m.getAttribute('data-thread-id') === activeThreadId,
      );
    });
  }, [activeThreadId, marks, content]);

  return (
    <>
      {editing ? (
        <textarea
          className="brief-edit-textarea"
          value={section.content}
          onChange={(e) => brief.editContent(section.id, e.target.value)}
          // Leaving the editor records the edit as a run of the section.
          onBlur={() => void brief.commitManualEdit(section.id)}
          rows={Math.min(28, Math.max(8, section.content.split('\n').length + 2))}
        />
      ) : versionEntry ? (
        <SectionVersionView
          entry={versionEntry}
          canRestore={!readOnly && !!versionEntry.restorable}
          onRestore={() => {
            onCloseVersion();
            void brief.restoreSectionEntry(section.id, versionEntry.id);
          }}
          onClose={onCloseVersion}
        />
      ) : review && showingChanges ? (
        <div className="brief-doc-content">
          <ReviewBar
            kind={review.kind}
            showingChanges
            busy={brief.isReviewBusy(section.id)}
            onToggle={onToggleChanges}
            onKeep={() => void brief.dismissChanges(section.id)}
            onReject={() => void brief.rejectChanges(section.id)}
          />
          <BriefDiff oldText={review.before} newText={content} />
        </div>
      ) : (
        <>
          {review && (
            <ReviewBar
              kind={review.kind}
              showingChanges={false}
              busy={brief.isReviewBusy(section.id)}
              onToggle={onToggleChanges}
              onKeep={() => void brief.dismissChanges(section.id)}
              onReject={() => void brief.rejectChanges(section.id)}
            />
          )}
          {factNote && (
            <div className="brief-fact-stale" role="note">
              <IconFactCheck /> {factNote}
            </div>
          )}
          <div
            className="brief-doc-content"
            ref={proseRef}
            onClick={(e) => {
              onSelectClaim?.(e.target);
              const bubble = (e.target as HTMLElement).closest(`.${BUBBLE_CLASS}`);
              const threadId = bubble?.getAttribute('data-thread-id');
              if (threadId && onOpenThread) onOpenThread(threadId);
            }}
          >
            <CitedMarkdown
              content={content}
              sources={sources}
              onSourceClick={onSourceClick}
              onRequestHighlight={onRequestHighlight}
            />
          </div>
        </>
      )}
      <CitedReferences
        content={content}
        sources={sources}
        onSourceClick={onSourceClick}
        collapsible
        labelPrefix="Evidence"
        className="brief-evidence"
        hidePages={brief.referenceGrouping === 'document-single'}
      />
    </>
  );
};

// Load a section's stored original (the agent's text, sources and trace)
// when the Log asks for one; a stale load never lands on a newer request.
const useRunOriginal = (
  brief: UseBriefReturn,
  sectionId: string,
  runId: string | null,
): { original: SectionRunDetail | null; originalError: string | null } => {
  const [original, setOriginal] = useState<SectionRunDetail | null>(null);
  const [originalError, setOriginalError] = useState<string | null>(null);
  const { getSectionRunDetail } = brief;
  useEffect(() => {
    if (!runId) return undefined;
    let cancelled = false;
    setOriginal(null);
    setOriginalError(null);
    getSectionRunDetail(sectionId, runId)
      .then((detail) => {
        if (!cancelled) setOriginal(detail);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setOriginalError(e instanceof Error ? e.message : 'Could not load the original.');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [getSectionRunDetail, sectionId, runId]);
  return { original, originalError };
};

// How an un-researched section invites research: inline panel (so instructions
// can be written for several sections before one "Regenerate all" run), the
// legacy button for un-edited sample headings, or nothing while busy/read-only.
type PendingMode = 'none' | 'inline' | 'button';

const pendingResearchMode = (
  section: BriefSection,
  panelOpen: boolean,
  anyResearching: boolean,
  readOnly: boolean,
): PendingMode => {
  if (section.status !== 'pending' || section.researchFailure || panelOpen || anyResearching || readOnly) {
    return 'none';
  }
  return section.sample ? 'button' : 'inline';
};

const SectionResearchFailure: React.FC<{
  section: BriefSection;
  brief: UseBriefReturn;
  readOnly: boolean;
  panelOpen: boolean;
  editingAi: boolean;
  busy: boolean;
}> = ({ section, brief, readOnly, panelOpen, editingAi, busy }) => {
  const failure = section.researchFailure;
  if (!failure || section.status === 'researching') return null;
  const action = failure.mode === 'generate' ? 'regeneration' : 'update';
  const retry = () => {
    if (failure.mode === 'update') {
      return brief.reviseSection(section.id, 'update', failure.instruction ?? null);
    }
    return brief.regenerate(section.id, section.guidance?.trim() || null);
  };
  return (
    <div className="brief-section-warning brief-research-failure">
      <div role="status">
        <strong>AI {action} failed</strong>
        <div>{failure.message}</div>
        {section.content && <div>You’re viewing the previous draft.</div>}
      </div>
      {!readOnly && !panelOpen && !editingAi && (
        <button type="button" className="brief-regen-btn" disabled={busy} onClick={retry}>
          <IconRefresh /> Retry {action}
        </button>
      )}
    </div>
  );
};

function SectionResearchControls({ section, brief, panelOpen, busy, locked, onSourceClick }:
  Pick<SectionViewProps, 'section' | 'brief' | 'onSourceClick'> & { panelOpen: boolean; busy: boolean; locked: boolean }) {
  const pendingMode = pendingResearchMode(section, panelOpen, busy, locked);
  return <>
    {(panelOpen || pendingMode === 'inline') && (
        <GuidancePanel section={section} brief={brief} hideCancel={pendingMode === 'inline'} />
      )}

      {pendingMode === 'button' && (
        <SectionPending sample onResearch={() => brief.openRegen(section.id)} />
      )}

      {section.status === 'researching' && (
        <SectionResearching section={section} onSourceClick={onSourceClick} />
      )}
  </>;
}

function SectionHeading({ section, num, brief, readOnly }: Pick<SectionViewProps, 'section' | 'num' | 'brief' | 'readOnly'>) {
  return (
      <div className="brief-doc-section-head">
        {num && <span className="brief-doc-section-num">{num}</span>}
        <input
          className="brief-doc-section-title"
          aria-label="Heading"
          value={section.title}
          onChange={(e) => brief.editTitle(section.id, e.target.value)}
          onBlur={brief.commitEdits}
          readOnly={readOnly}
        />
        {section.status === 'done' && (
          <span className="brief-doc-section-words" title={sectionWordsTitle(section, brief.targetWords)}>
            {countWords(section.content).toLocaleString()} words
          </span>
        )}
      </div>
  );
}

const BriefSectionView: React.FC<SectionViewProps> = ({
  section,
  num,
  brief,
  onSourceClick,
  readOnly = false,
  checkingFacts = false,
  onRequestHighlight,
  marks,
  onOpenThread,
  activeThreadId,
  factMarks,
  factNote,
  onSelectClaim,
}) => {
  const [editing, setEditing] = useState(false);
  // The stored original being viewed from the Log, and its load state.
  const [originalRunId, setOriginalRunId] = useState<string | null>(null);
  const { original, originalError } = useRunOriginal(brief, section.id, originalRunId);
  // AI Edit/Update instruction panel + audit modal + changes toggle.
  const [aiPanel, setAiPanel] = useState<null | 'edit' | 'update'>(null);
  const [aiText, setAiText] = useState('');
  const [logOpen, setLogOpen] = useState(false);
  const locked = readOnly || checkingFacts;
  const changes = useSectionChanges(section, locked);
  const panelOpen = !checkingFacts && brief.regenFor === section.id;
  const isDone = section.status === 'done';
  const anyResearching = brief.researching || checkingFacts;
  const audit = section.audit ?? [];
  const auditCount = audit.length;
  // Signed-in users who can open the brief see the Log; a brief kept only in
  // this browser has no stored history to show.
  const showLog = brief.remote;
  const openRegeneration = () => brief.openRegen(section.id);
  const submitAi = () => {
    const panel = aiPanel;
    if (!panel) return;
    setAiPanel(null);
    changes.closeVersion();
    brief.reviseSection(section.id, panel, aiText.trim() || null);
    setAiText('');
  };

  return (
    <BriefSectionFrame researching={section.status === 'researching'}
      id={`brief-section-${section.id}`}
      data-brief-section-id={section.id}
      className={`brief-doc-section${section.level === 2 ? ' brief-doc-section-sub' : ''}`}
    >
      <SectionHeading section={section} num={num} brief={brief} readOnly={locked} />

      <SectionResearchFailure
        section={section}
        brief={brief}
        readOnly={readOnly}
        panelOpen={panelOpen}
        editingAi={Boolean(aiPanel)}
        busy={anyResearching}
      />

      {/* The owner gets the section tools; a signed-in viewer gets the Log. */}
      {isDone && readOnly && (
        <ViewerLogButton show={showLog} auditCount={auditCount} onOpen={() => setLogOpen(true)} />
      )}
      {isDone && !readOnly && (
        <SectionTools checkingFacts={checkingFacts}
          title={section.title}
          editing={editing}
          auditCount={auditCount}
          showLog={showLog}
          onToggleEdit={() => setEditing((v) => !v)}
          onRegenerate={openRegeneration}
          regenerationFailed={section.researchFailure?.mode === 'generate'}
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

      <IntroHeadingWarning headings={isDone ? section.introHeadingWarning : undefined} />
      {isDone && (
        <UnresolvedCitationsWarning
          unresolved={section.unresolved}
          canOpenLog={showLog}
          onOpenLog={() => setLogOpen(true)}
        />
      )}

      {aiPanel && !checkingFacts && (
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
          pendingRunId={changes.pendingRunId}
          // Clicking a row opens that version compared with the one before
          // it; the change awaiting review opens its tracked changes.
          onShowChanges={(entryId) => {
            setLogOpen(false);
            changes.openEntry(entryId);
          }}
          runs={section.runs || []}
          onViewOriginal={(runId) => {
            setLogOpen(false);
            setOriginalRunId(runId);
          }}
          onClose={() => setLogOpen(false)}
        />
      )}

      {originalRunId && (
        <BriefRunOriginal
          title={section.title}
          detail={original}
          error={originalError}
          onClose={() => setOriginalRunId(null)}
        />
      )}

      <SectionResearchControls section={section} brief={brief} panelOpen={panelOpen}
        busy={anyResearching} locked={locked} onSourceClick={onSourceClick} />

      {isDone && (
        <SectionDoneBody
          section={section}
          brief={brief}
          editing={editing && !checkingFacts}
          readOnly={locked}
          versionEntry={changes.versionEntry}
          onCloseVersion={changes.closeVersion}
          reviewOpen={changes.reviewOpen}
          showingChanges={changes.showingChanges}
          onToggleChanges={changes.toggleChanges}
          onSourceClick={onSourceClick}
          onRequestHighlight={onRequestHighlight}
          marks={marks}
          onOpenThread={onOpenThread}
          activeThreadId={activeThreadId}
          factMarks={factMarks}
          factNote={factNote}
          onSelectClaim={onSelectClaim}
        />
      )}
    </BriefSectionFrame>
  );
};

function FactCheckLegend({ factCheck }: { factCheck?: UseBriefFactCheckReturn }) {
  return <>{factCheck?.active && <div className="brief-fact-legend" role="group" aria-label="Fact check results">
          <strong>Showing fact check results</strong>
          {factCheck.legend.filter(item => item.count > 0).map(item => <span key={item.verdict} className="brief-fact-legend-item">
            <span className={`brief-fact-swatch brief-fact-mark-${item.verdict}`} />{item.label} {item.count}
          </span>)}
          <button type="button" className="brief-fact-hide" onClick={factCheck.toggle}>Hide results</button>
        </div>}
        {factCheck?.notice && <p role="status">{factCheck.notice}</p>}</>;
}

const FactCheckButton = ({ factCheck }: { factCheck: UseBriefFactCheckReturn }) => (
  <BriefActionMenu label="Fact Checker" buttonText="Fact Checker" icon={IconFactCheck}
    buttonClass="brief-export-word brief-fact-check" actions={[
      { label: 'Run Fact Checker', icon: IconFactCheck, onSelect: factCheck.start,
        disabled: !!factCheck.disabledReason || !!factCheck.run || factCheck.busy,
        title: factCheck.disabledReason || undefined },
      { label: factCheck.active ? 'Hide results' : 'Show Fact Checks', icon: IconFactCheck,
        onSelect: factCheck.toggle, disabled: !factCheck.available, title: factCheck.note },
    ]} />
);

// The document-level action row: regenerate/update all, share, save-as-template
// and the Word export menu. Owner-only actions are hidden for viewers.
const HeaderActions: React.FC<{
  brief: UseBriefReturn;
  readOnly: boolean;
  canEditStructure: boolean;
  onOpenShare?: () => void;
  onSaveTemplate?: () => void;
  onRegenerateAll?: () => void;
  onExportWord?: () => void;
  exportBusy?: boolean;
  factCheck?: UseBriefFactCheckReturn;
  onHistory: () => void;
}> = ({
  brief,
  readOnly,
  canEditStructure,
  onOpenShare,
  onSaveTemplate,
  onRegenerateAll,
  onExportWord,
  exportBusy,
  factCheck,
  onHistory,
}) => {
  const { toolbarRef, compact } = useDocumentActionLayout();
  const { sections } = brief;
  const hasSections = sections.length > 0;
  const aiActions = [{
    label: 'AI Regenerate All Sections',
    icon: IconRefresh,
    onSelect: onRegenerateAll || (() => void brief.startResearch()),
    title: 'Re-research every section from scratch',
  }];
  if (sections.some((section) => section.status === 'done')) {
    aiActions.push({
      label: 'AI Get Updates for All Sections',
      icon: IconClock,
      onSelect: brief.updateAll,
      title: 'Fold sources published since each section was last run into every researched section',
    });
  }
  const moreActions: BriefAction[] = [];
  if (!readOnly && onOpenShare) moreActions.push({ label: 'Share', icon: IconShare, onSelect: onOpenShare });
  if (!readOnly && onSaveTemplate && hasSections) moreActions.push({ label: 'Save as Template', icon: IconCopy, onSelect: onSaveTemplate, align: 'end' });
  if (onExportWord) moreActions.push({ label: exportBusy ? 'Exporting…' : 'Export to Word', icon: IconDownload, onSelect: onExportWord, align: 'end', disabled: !hasSections || exportBusy });
  if (brief.remote && hasSections) moreActions.push({ label: 'Document History' + (brief.versionCount ? ' (' + brief.versionCount + ')' : ''), icon: IconClock, onSelect: onHistory, align: 'end' });
  return (
    <div ref={toolbarRef} className="brief-doc-header-actions" role="group" aria-label="Whole document actions">
      {!readOnly && hasSections && (
        <DocumentAiActions actions={aiActions} disabled={!canEditStructure} compact={compact} />
      )}
      {factCheck && <FactCheckButton factCheck={factCheck} />}
      <BriefDocumentActions actions={moreActions} compact={compact} />
    </div>
  );
};

interface BriefDocumentProps {
  brief: UseBriefReturn;
  onResultClick?: (result: SearchResult) => void;
  // Export the brief to Word. 'links' keeps inline [n] citations; 'footnotes'
  // renders each citation as a Word footnote on the relevant page.
  onExportWord?: () => void;
  exportBusy?: boolean;
  // Brief Central integrations (remote mode only).
  onOpenShare?: () => void;
  onSaveTemplate?: () => void;
  onRegenerateAll?: () => void;
  // False when the Contents panel renders in the workspace side rail instead
  // (logged-in layout); true keeps the inline panel (anonymous layout).
  showToc?: boolean;
  // Selecting text inside a section surfaces the selection toolbar; the owner
  // decides which actions to offer.
  onSelectText?: (selection: BriefSelection) => void;
  // Commented passages to paint into the prose, keyed by section id.
  commentMarks?: Map<string, CommentMark[]>;
  // A speech bubble in the text was clicked.
  onOpenThread?: (threadId: string) => void;
  // Comment visibility, and the control for it shown in the meta row.
  showComments?: boolean;
  onToggleComments?: (show: boolean) => void;
  // The thread being viewed, so its passage can be shown as active.
  activeThreadId?: string | null;
  // The Fact Checker of the open brief (remote mode only).
  factCheck?: UseBriefFactCheckReturn;
}

// Floating bar fixed to the bottom of the viewport while research runs: which
// section is being written, overall progress, and a Stop control.
const ResearchStatusBar: React.FC<{ brief: UseBriefReturn }> = ({ brief }) => {
  const current = brief.sections.find((s) => s.status === 'researching');
  if (!current) return null;
  const total = brief.regeneration?.total ?? brief.sections.length;
  return <ProgressBar label={`${current.revising ? 'Revising' : 'Researching'} “${current.title}”`}
    count={brief.regenerating ? `${brief.updatedCount} of ${total} updated` : `${brief.doneCount}/${total} sections`}
    percent={brief.totalProgress} stop={brief.stopResearch} stopLabel="Stop all research" />;
};

function FactCheckProgress({ check }: { check: UseBriefFactCheckReturn }) {
  if (!check.run) return null;
  const progress = check.run.progress;
  const heading = progress?.remaining_sections?.[0]?.heading;
  return <ProgressBar label={heading ? `Checking “${heading}”` : 'Checking facts…'}
    count={progress ? `${progress.completed} of ${progress.total} sections checked` : 'Starting…'}
    percent={progress?.total ? 100 * progress.completed / progress.total : 0}
    stop={check.stop} stopLabel="Stop fact check" stopping={check.busy || check.run.stopped} />;
}

const ProgressBar = ({ label, count, percent, stop, stopLabel, stopping }: {
  label: string; count: string; percent: number; stop: () => void; stopLabel: string; stopping?: boolean;
}) => (
    <div className="brief-status-bar" role="status">
      <span className="brief-spinner brief-status-bar-spinner" />
      <div className="brief-status-bar-main">
        <div className="brief-status-bar-label">
          {label}<span className="brief-status-bar-count">{count}</span>
        </div>
        <div className="brief-status-bar-track">
          <div className="brief-status-bar-fill" style={{ width: `${percent}%` }} />
        </div>
      </div>
      <button
        className="brief-status-bar-stop"
        onClick={stop} disabled={stopping}
        aria-label={stopLabel} title={stopLabel}
      >
        {stopping ? 'Stopping…' : 'Stop'}
      </button>
    </div>
  );

// The selection the reader just made inside a section, or null. The section
// is resolved from the DOM so nested markup (links, citations) still traces
// back to it.
const selectionInSection = (): BriefSelection | null => {
  const sel = window.getSelection();
  const text = sel ? sel.toString().trim() : '';
  if (!sel || !text || text.length < 3 || sel.rangeCount !== 1) return null;
  const node = sel.anchorNode;
  const el = node instanceof HTMLElement ? node : (node?.parentElement as HTMLElement | null);
  const sectionEl = el?.closest('[data-brief-section-id]') as HTMLElement | null;
  const sectionId = sectionEl?.getAttribute('data-brief-section-id');
  if (!sectionId) return null;
  const range = sel.getRangeAt(0);
  const box = range.getBoundingClientRect();
  // One rect per line, so a multi-line selection stays fully marked.
  const rects = Array.from(range.getClientRects()).map((r) => ({
    top: r.top,
    left: r.left,
    width: r.width,
    height: r.height,
  }));
  return { sectionId, text, rect: { top: box.top, left: box.left, width: box.width }, rects };
};

// The line under the title: counts, the viewer chip, the outline log toggle
// and the comments switch.
const BriefMeta: React.FC<{
  brief: UseBriefReturn;
  readOnly: boolean;
  hasOutlineLog: boolean;
  logOpen: boolean;
  onToggleLog: () => void;
  showComments?: boolean;
  onToggleComments?: (show: boolean) => void;
}> = ({ brief, readOnly, hasOutlineLog, logOpen, onToggleLog, showComments, onToggleComments }) => (
  <div className="brief-doc-meta">
    <span>{brief.sections.length} sections</span>
    <span>·</span>
    <span>{brief.totalSources} sources synthesised</span>
    {brief.totalWords > 0 && (
      <>
        <span>·</span>
        <span>{brief.totalWords.toLocaleString()} words</span>
      </>
    )}
    {readOnly && brief.ownerName && (
      <>
        <span>·</span>
        <span className="brief-viewer-chip">Owned by {brief.ownerName} — view only</span>
      </>
    )}
    {hasOutlineLog && (
      <>
        <span>·</span>
        <button className="brief-meta-link" onClick={onToggleLog} aria-expanded={logOpen}>
          Outline analysis
        </button>
      </>
    )}
    {onToggleComments && brief.sections.length > 0 && (
      <label className="brief-comments-visibility" title="Show or hide comments on this brief">
        <input
          type="checkbox"
          checked={showComments !== false}
          onChange={(e) => onToggleComments(e.target.checked)}
        />
        Show comments
      </label>
    )}
  </div>
);

// The document-wide progress row shown while research runs.
const ResearchProgress: React.FC<{ brief: UseBriefReturn }> = ({ brief }) => (
  <div className="brief-doc-progress">
    <div className="brief-doc-progress-row">
      <span>Researching…</span>
      <span className="brief-doc-progress-right">
        {brief.doneCount}/{brief.sections.length}
        <button className="brief-stop-btn" onClick={brief.stopResearch} title="Stop all research">
          ■ Stop
        </button>
      </span>
    </div>
    <div className="brief-progress-track">
      <div className="brief-progress-fill" style={{ width: `${brief.totalProgress}%` }} />
    </div>
  </div>
);

const RegenerationResult: React.FC<{ brief: UseBriefReturn }> = ({ brief }) => {
  const result = brief.regeneration;
  if (brief.regenerating || (!result && !brief.failedGenerationCount)) return null;
  const canRetry = brief.canEdit && brief.failedGenerationCount > 0;
  return (
    <div className="brief-doc-progress brief-regeneration-result">
      <div role="status">
        {result && <div>Updated {brief.updatedCount} of {result.total} sections.</div>}
        {canRetry && <div>Sections that failed are marked in Contents.</div>}
      </div>
      {canRetry && (
        <button
          type="button"
          className="brief-regen-btn"
          disabled={brief.researching}
          onClick={() => void brief.retryFailedSections()}
        >
          <IconRefresh /> Retry failed sections ({brief.failedGenerationCount})
        </button>
      )}
    </div>
  );
};

// The outline-generation activity log (queries run, sources read).
const OutlineLog: React.FC<{ brief: UseBriefReturn; onClose: () => void }> = ({ brief, onClose }) => (
  <div className="brief-outline-log">
    <div className="brief-outline-log-head">
      <span>Outline research — queries run and sources read</span>
      <button
        className="brief-outline-log-close"
        onClick={onClose}
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
);

export const BriefDocument: React.FC<BriefDocumentProps> = ({
  brief,
  onResultClick,
  onExportWord,
  exportBusy,
  onOpenShare,
  onSaveTemplate,
  onRegenerateAll,
  showToc = true,
  onSelectText,
  commentMarks,
  onOpenThread,
  activeThreadId,
  showComments,
  onToggleComments,
  factCheck,
}) => {
  const { sections, numbers } = brief;
  const [logOpen, setLogOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const hasOutlineLog = brief.generatingActivity.length > 0;


  // Viewer-only: a brief shared with (not owned by) this user renders read-only.
  const checkingFacts = !!(factCheck?.run || factCheck?.busy);
  const readOnly = !brief.canEdit;
  // Structural edits (reorder/add/remove via the TOC) lock while research runs.
  const editingLocked = readOnly || checkingFacts;
  const canEditStructure = !editingLocked && !brief.researching;

  // A cited excerpt from the Fact Checker's card, opened the same way.
  const handleEvidenceClick = (source: BriefFactCheckEvidence) => {
    if (!onResultClick) return;
    onResultClick({
      chunk_id: source.chunk_id || '',
      doc_id: source.doc_id || '',
      title: source.title,
      text: source.segments.map((segment) => segment.text).join(''),
      page_num: source.page || 1,
      score: 0,
      headings: source.section ? source.section.split(' > ') : [],
      report_url: source.pdf_url || undefined,
      metadata: {},
    });
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

  // Report a selection made inside a section (comments anchor to it).
  const handleMouseUp = () => {
    if (!onSelectText) return;
    const selection = selectionInSection();
    if (selection) onSelectText(selection);
  };

  return (
    <div className="brief-doc" onMouseUp={handleMouseUp}>
      <div className="brief-doc-header">
          <HeaderActions
            brief={brief}
            readOnly={readOnly}
            canEditStructure={canEditStructure}
            onOpenShare={onOpenShare}
            onSaveTemplate={onSaveTemplate}
            onRegenerateAll={onRegenerateAll}
            onExportWord={onExportWord}
            exportBusy={exportBusy}
            factCheck={factCheck}
            onHistory={() => setVersionsOpen(true)}
          />
        <FactCheckLegend factCheck={factCheck} />
        <div className="brief-doc-header-top">
          <div className="brief-eyebrow">EVIDENCE BRIEF</div>

        </div>
        <div className="brief-title-row">
          <AutoGrowTextarea
            className="brief-doc-title-input"
            value={brief.briefTitle}
            onChange={(e) => {
              brief.setBriefTitle(e.target.value);
            }}
            onBlur={brief.commitEdits}
            rows={1}
            aria-label="Brief title"
            readOnly={editingLocked}
          />

        </div>

        {versionsOpen && (
          <BriefVersionsModal
            briefId={brief.getServerBriefId()}
            readOnly={editingLocked}
            onRestore={brief.restoreBriefVersion}
            onClose={() => setVersionsOpen(false)}
          />
        )}
        <BriefMeta
          brief={brief}
          readOnly={readOnly}
          hasOutlineLog={hasOutlineLog}
          logOpen={logOpen}
          onToggleLog={() => setLogOpen((v) => !v)}
          showComments={showComments}
          onToggleComments={onToggleComments}
        />
        {brief.stage === 'research' && brief.researching && !brief.regenerating && <ResearchProgress brief={brief} />}
        <RegenerationResult brief={brief} />
        {logOpen && hasOutlineLog && <OutlineLog brief={brief} onClose={() => setLogOpen(false)} />}
      </div>

      {showToc && sections.length > 0 && <BriefToc brief={brief} canEdit={canEditStructure} />}

      {sections.map((s, i) => (
        <BriefSectionView
          key={s.id}
          section={s}
          num={brief.numberHeadings ? numbers[i] : ''}
          brief={brief}
          onSourceClick={handleSourceClick}
          readOnly={readOnly}
          onRequestHighlight={(src, claim) =>
            src.chunkId ? brief.requestSourceHighlight(s.id, src.chunkId, claim) : undefined
          }
          marks={showComments === false ? undefined : commentMarks?.get(s.id)}
          onOpenThread={onOpenThread}
          activeThreadId={activeThreadId}
          checkingFacts={checkingFacts}
          factMarks={factCheck?.marks.get(s.id)}
          factNote={factCheck?.changedSections.get(s.id)?.note}
          onSelectClaim={factCheck?.selectClaim}
        />
      ))}

      {brief.stage === 'outline' && !readOnly && (
        <div className="brief-doc-actions">
          <button
            className="brief-btn brief-btn-primary"
            onClick={onRegenerateAll || (() => void brief.startResearch())}
            disabled={!sections.length || checkingFacts}
          >
            Start deep research →
          </button>
        </div>
      )}

      <BriefReferences
        references={brief.references}
        groups={brief.referenceGroups}
        locked={checkingFacts}
        grouping={brief.referenceGrouping}
        onGroupingChange={brief.setReferenceGrouping}
        onSourceClick={handleSourceClick}
        wordLinkTarget={brief.wordLinkTarget}
        onWordLinkTargetChange={brief.setWordLinkTarget}
      />

      <div className="brief-progress-stack">
        <ResearchStatusBar brief={brief} />
        {factCheck && <FactCheckProgress check={factCheck} />}
      </div>
      {factCheck?.selectedClaim && <BriefClaimDialog
        mark={factCheck.selectedClaim}
        onClose={factCheck.closeClaim}
        evidence={factCheck.evidence}
        onOpenSource={onResultClick ? handleEvidenceClick : undefined}
      />}
    </div>
  );
};
