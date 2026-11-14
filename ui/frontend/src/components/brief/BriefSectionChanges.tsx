import React, { useEffect, useRef, useState } from 'react';
import { BriefDiff } from './BriefDiff';
import { formatWhen, KIND_LABEL } from './BriefSectionAudit';
import { BriefSection, SectionAuditEntry, SectionAuditKind } from './briefTypes';

// A section's changes: the review bar over a single-section Generate, Edit or
// Update awaiting Keep or Reject, and an earlier version opened from the Log.

// What a change was, for the review bar and the version view headings.
const CHANGE_NOUN: Record<SectionAuditKind, string> = {
  generate: 'regeneration',
  edit: 'AI edit',
  update: 'update',
  condense: 'condense pass',
  manual: 'manual edit',
  restore: 'restore',
};

// The buttons over a section whose single-section Generate, Edit or Update
// awaits review: show or hide the tracked changes, keep them or reject them.
export const ReviewBar: React.FC<{
  kind: SectionAuditKind;
  showingChanges: boolean;
  onToggle: () => void;
  onKeep: () => void;
  onReject: () => void;
}> = ({ kind, showingChanges, onToggle, onKeep, onReject }) => (
  <div className="brief-diff-head brief-review-bar">
    <span className="brief-diff-actions">
      <button
        className="brief-diff-dismiss brief-diff-hide"
        onClick={onToggle}
        title={
          showingChanges
            ? 'Show just the new text'
            : `Show the tracked changes from the ${CHANGE_NOUN[kind]}`
        }
      >
        {showingChanges ? 'Hide Changes' : 'Show Changes'}
      </button>
      <button className="brief-diff-dismiss brief-diff-keep" onClick={onKeep}>
        Keep Edits
      </button>
      <button className="brief-diff-dismiss brief-diff-reject" onClick={onReject}>
        Reject Edits
      </button>
    </span>
  </div>
);

// "Edited Nov 13 · 7:02 PM (rejected), compared with the version before it".
const versionHeading = (entry: SectionAuditEntry): string => {
  const notes: string[] = [];
  if (entry.status === 'rejected') notes.push('rejected');
  if (entry.current) notes.push('current version');
  const suffix = notes.length ? ` (${notes.join(', ')})` : '';
  return `${KIND_LABEL[entry.kind]} ${formatWhen(entry.at)}${suffix}, compared with the version before it`;
};

// An earlier version of a section opened from its Log: that version compared
// with the one before it, and (for the owner) a way to bring it back.
export const SectionVersionView: React.FC<{
  entry: SectionAuditEntry;
  canRestore: boolean;
  onRestore: () => void;
  onClose: () => void;
}> = ({ entry, canRestore, onRestore, onClose }) => (
  <div className="brief-doc-content">
    <div className="brief-diff-head">
      <span>{versionHeading(entry)}</span>
      <span className="brief-diff-actions">
        {canRestore && (
          <button className="brief-diff-dismiss brief-diff-keep" onClick={onRestore}>
            Restore this version
          </button>
        )}
        <button
          className="brief-diff-close"
          onClick={onClose}
          title="Back to the current text"
          aria-label="Close this version"
        >
          ×
        </button>
      </span>
    </div>
    <BriefDiff oldText={entry.before || ''} newText={entry.after || ''} />
  </div>
);

// What a section shows of its changes: the Log row whose version is open, and
// whether a change awaiting review shows as tracked changes. A viewer cannot
// keep or reject, so for them nothing awaits review.
export const useSectionChanges = (section: BriefSection, readOnly: boolean) => {
  const [versionEntryId, setVersionEntryId] = useState<string | null>(null);
  const audit = section.audit ?? [];
  const pendingRunId = readOnly ? null : section.pendingReview?.runId ?? null;
  // A change already awaiting review when the brief opens shows as plain
  // text, with no review buttons. The review (tracked changes, Keep and
  // Reject) opens for a change made while the brief is open, or when the
  // change is chosen from the Section History.
  const [hideChanges, setHideChanges] = useState(true);
  const [reviewOpen, setReviewOpen] = useState(false);
  const openReview = (): void => {
    setReviewOpen(true);
    setHideChanges(false);
  };
  const seenPendingRunId = useRef(pendingRunId);
  useEffect(() => {
    if (pendingRunId && pendingRunId !== seenPendingRunId.current) {
      setReviewOpen(true);
      setHideChanges(false);
      setVersionEntryId(null);
    }
    seenPendingRunId.current = pendingRunId;
  }, [pendingRunId]);
  // A Log row opens its version; the row of the change awaiting review opens
  // the review itself.
  const openEntry = (entryId: string): void => {
    const entry = audit.find((e) => e.id === entryId);
    const isPending = !!pendingRunId && entry?.runId === pendingRunId;
    setVersionEntryId(isPending ? null : entryId);
    if (isPending) openReview();
  };
  return {
    versionEntry: versionEntryId ? audit.find((e) => e.id === versionEntryId) ?? null : null,
    closeVersion: () => setVersionEntryId(null),
    showingChanges: !hideChanges,
    toggleChanges: () => setHideChanges((v) => !v),
    reviewOpen,
    pendingRunId,
    openEntry,
  };
};
