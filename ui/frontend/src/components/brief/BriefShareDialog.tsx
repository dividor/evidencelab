import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  LibraryKind,
  addBriefShare,
  addLibraryShare,
  getBrief,
  listLibraryShares,
  removeBriefShare,
  removeLibraryShare,
  searchShareTargets,
} from './briefCentralApi';
import { IconCopy } from './BriefIcons';
import { BriefShareTarget } from './briefTypes';

/**
 * The Share dialog, used for briefs, templates and voice & tone profiles.
 * Everything is shared with a person (by email) or a group (by name); what
 * the recipients may do depends on the item, which the wrappers below say.
 */

const errMessage = (e: unknown, fallback: string): string =>
  e instanceof Error ? e.message : fallback;

const initialsOf = (name: string): string =>
  name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

interface ShareSuggestion {
  value: string;
  label: string;
  sub: string;
  kind: 'user' | 'group';
}

// Suggestions for what has been typed: the API matches people by email or
// name and groups by name, so the user picks a real target instead of
// guessing an exact address. Debounced so a lookup runs when typing pauses.
const useShareSuggestions = (input: string) => {
  const [suggestions, setSuggestions] = useState<ShareSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const term = input.trim();
    if (term.length < 2) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      void searchShareTargets(term)
        .then((res) => {
          if (cancelled) return;
          setSuggestions([
            ...res.users.map((u) => ({ value: u.email, label: u.name, sub: u.email, kind: 'user' as const })),
            ...res.groups.map((g) => ({ value: g.name, label: g.name, sub: 'Group', kind: 'group' as const })),
          ]);
          setOpen(true);
        })
        .catch(() => {
          if (!cancelled) setSuggestions([]);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [input]);
  return { suggestions, open, setOpen };
};

export interface ShareDialogProps {
  title: string;
  subtitle: string;
  // What a recipient gets, shown beside each person or group ("Viewer", "Can use").
  accessLabel: string;
  load: () => Promise<BriefShareTarget[]>;
  add: (target: string) => Promise<BriefShareTarget[]>;
  remove: (shareId: string) => Promise<void>;
  onChanged?: (targets: BriefShareTarget[]) => void;
  onClose: () => void;
  // Extra content above "Add people or groups" (the brief's link).
  children?: React.ReactNode;
}

export const ShareDialog: React.FC<ShareDialogProps> = ({
  title,
  subtitle,
  accessLabel,
  load,
  add,
  remove,
  onChanged,
  onClose,
  children,
}) => {
  const [targets, setTargets] = useState<BriefShareTarget[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { suggestions, open: suggestOpen, setOpen: setSuggestOpen } = useShareSuggestions(input);
  // The suggestion picked with the arrow keys (-1 = none; Enter adds what was typed).
  const [active, setActive] = useState(-1);
  const showSuggestions = suggestOpen && suggestions.length > 0;

  // Load once when the dialog opens; callers pass a new `load` each render.
  const loadRef = useRef(load);
  useEffect(() => {
    let cancelled = false;
    loadRef
      .current()
      .then((list) => {
        if (!cancelled) setTargets(list);
      })
      .catch((e) => {
        if (!cancelled) setError(errMessage(e, 'Could not load sharing.'));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Share with `picked` (a chosen suggestion) or, without one, what was typed.
  const submit = useCallback(
    async (picked?: string) => {
      const target = (picked ?? input).trim();
      if (!target || busy) return;
      setBusy(true);
      setError(null);
      setSuggestOpen(false);
      setActive(-1);
      try {
        const updated = await add(target);
        setTargets(updated);
        setInput('');
        onChanged?.(updated);
      } catch (e) {
        setInput(target);
        setError(errMessage(e, 'Could not share.'));
      } finally {
        setBusy(false);
      }
    },
    [input, busy, add, onChanged, setSuggestOpen],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' && suggestions.length > 0) {
      e.preventDefault();
      setSuggestOpen(true);
      setActive((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp' && showSuggestions) {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const chosen = showSuggestions ? suggestions.find((_, i) => i === active) : undefined;
      void submit(chosen?.value);
    } else if (e.key === 'Escape') {
      setSuggestOpen(false);
      setActive(-1);
    }
  };

  const revoke = useCallback(
    async (shareId: string) => {
      setError(null);
      try {
        await remove(shareId);
        const updated = targets.filter((t) => t.id !== shareId);
        setTargets(updated);
        onChanged?.(updated);
      } catch (e) {
        setError(errMessage(e, 'Could not remove access.'));
      }
    },
    [remove, targets, onChanged],
  );

  return (
    <div className="brief-modal-overlay" onClick={onClose}>
      <div className="brief-modal bc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">{title}</div>
            <div className="brief-modal-sub">{subtitle}</div>
          </div>
          <button className="brief-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bc-modal-body">
          {error && <div className="brief-error">{error}</div>}
          {children}

          <label className="brief-label brief-label-spaced" htmlFor="bc-share-add">
            Add people or groups
          </label>
          <div className="bc-share-row">
            <input
              id="bc-share-add"
              className="bc-input"
              value={input}
              autoComplete="off"
              role="combobox"
              aria-expanded={showSuggestions}
              aria-controls="bc-share-suggestions"
              onChange={(e) => {
                setInput(e.target.value);
                setSuggestOpen(true);
                setActive(-1);
              }}
              onKeyDown={onKeyDown}
              onFocus={() => suggestions.length > 0 && setSuggestOpen(true)}
              placeholder="Search people or groups"
            />
            <button className="brief-btn brief-btn-primary" disabled={busy} onClick={() => void submit()}>
              Add
            </button>
          </div>
          {/* In the normal flow, not floating: the dialog scrolls, and a floating
              list would be clipped at its edge. Choosing a suggestion shares
              with it straight away. */}
          {showSuggestions && (
            <div id="bc-share-suggestions" className="bc-share-suggestions" role="listbox">
              {suggestions.map((sug, i) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  className={`bc-share-suggestion${i === active ? ' bc-share-suggestion-active' : ''}`}
                  key={`${sug.kind}-${sug.value}`}
                  disabled={busy}
                  onClick={() => void submit(sug.value)}
                >
                  <span className="bc-avatar">{initialsOf(sug.label)}</span>
                  <span className="bc-share-suggestion-main">
                    <span className="bc-share-suggestion-name">{sug.label}</span>
                    <span className="bc-share-suggestion-sub">{sug.sub}</span>
                  </span>
                  <span className="bc-share-suggestion-add">Share</span>
                </button>
              ))}
            </div>
          )}

          <div className="bc-share-list">
            {targets.map((t) => (
              <div key={t.id} className="bc-share-item">
                <span className="bc-avatar">{initialsOf(t.name)}</span>
                <div className="bc-share-item-main">
                  <div className="bc-share-item-name">{t.name}</div>
                  <div className="bc-share-item-kind">{t.kind}</div>
                </div>
                <span className="bc-viewer-chip">{accessLabel}</span>
                <button
                  className="bc-icon-btn bc-icon-danger"
                  title="Remove access"
                  aria-label={`Remove access for ${t.name}`}
                  onClick={() => void revoke(t.id)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          <div className="bc-modal-actions">
            <button className="brief-btn brief-btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

/** Share a brief: viewer-only, with a link recipients can open. */
export const BriefShareModal: React.FC<{
  briefId: string;
  briefTitle: string;
  onChanged?: () => void;
  onClose: () => void;
}> = ({ briefId, briefTitle, onChanged, onClose }) => {
  const [copied, setCopied] = useState(false);
  const shareUrl = `${window.location.origin}/brief/${briefId}`;
  const copy = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(shareUrl).catch(() => {});
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <ShareDialog
      title={`Share “${briefTitle}”`}
      subtitle="People you add can read this brief. Only you can edit it."
      accessLabel="Viewer"
      load={async () => (await getBrief(briefId)).shared_with}
      add={async (target) => (await addBriefShare(briefId, target)).shared_with}
      remove={(shareId) => removeBriefShare(briefId, shareId)}
      onChanged={() => onChanged?.()}
      onClose={onClose}
    >
      <label className="brief-label" htmlFor="bc-share-url">
        Brief link
      </label>
      <div className="bc-share-row">
        <input id="bc-share-url" className="bc-input bc-share-url" readOnly value={shareUrl} />
        <button className="brief-btn brief-btn-secondary" onClick={copy}>
          <IconCopy size={14} />
          {copied ? 'Copied' : 'Copy link'}
        </button>
      </div>
      <div className="bc-hint">Only people and groups added below can open this link.</div>
    </ShareDialog>
  );
};

const librarySubtitle = (kind: LibraryKind): string =>
  kind === 'template'
    ? 'People you add can start briefs from this template and make their own copy. The voice & tone profiles it uses that you own are shared with them too. Only you can edit it, and your changes reach them.'
    : 'People you add can write with this voice & tone profile and make their own copy. Only you can edit it, and your changes reach them.';

/** Share a template or a voice & tone profile: use-only. */
export const LibraryShareModal: React.FC<{
  kind: LibraryKind;
  itemId: string;
  itemName: string;
  onChanged?: (shareCount: number) => void;
  onClose: () => void;
}> = ({ kind, itemId, itemName, onChanged, onClose }) => (
  <ShareDialog
    title={`Share “${itemName}”`}
    subtitle={librarySubtitle(kind)}
    accessLabel="Can use"
    load={() => listLibraryShares(kind, itemId)}
    add={(target) => addLibraryShare(kind, itemId, target)}
    remove={(shareId) => removeLibraryShare(kind, itemId, shareId)}
    onChanged={(targets) => onChanged?.(targets.length)}
    onClose={onClose}
  />
);
