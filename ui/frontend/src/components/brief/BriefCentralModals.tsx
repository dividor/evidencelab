import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { addBriefShare, getBrief, removeBriefShare } from './briefCentralApi';
import { IconCopy, IconPlus, IconSparkle } from './BriefIcons';
import {
  BriefShareTarget,
  BriefTemplate,
  BriefTemplateHeading,
  VoiceProfile,
} from './briefTypes';

/**
 * The Brief Central modals: New brief, template editor (new + save-from-brief),
 * voice & tone profile editor, and viewer-only sharing. All reuse the existing
 * `.brief-modal-*` shell classes plus `.bc-*` styles from brief.css.
 */

const errMessage = (e: unknown, fallback: string): string =>
  e instanceof Error ? e.message : fallback;

// Numbering matching the brief document: 1, 1.1, 1.2, 2, …
export const numberHeadings = (
  headings: BriefTemplateHeading[],
): { num: string; title: string; sub: boolean }[] => {
  let top = 0;
  let sub = 0;
  return headings.map((h) => {
    if (h.sub && top > 0) {
      sub += 1;
      return { num: `${top}.${sub}`, title: h.title, sub: true };
    }
    top += 1;
    sub = 0;
    return { num: `${top}`, title: h.title, sub: false };
  });
};

// ---------------------------------------------------------------------------
// New brief
// ---------------------------------------------------------------------------

export interface NewBriefSubmit {
  mode: 'ai' | 'manual';
  title: string;
  instructions: string;
  voiceId: string | null;
  numHeadings: number;
  template: BriefTemplate | null;
}

export const BriefNewModal: React.FC<{
  templates: BriefTemplate[];
  voices: VoiceProfile[];
  initialTemplateId?: string | null;
  onSubmit: (args: NewBriefSubmit) => void;
  onClose: () => void;
}> = ({ templates, voices, initialTemplateId, onSubmit, onClose }) => {
  const [mode, setMode] = useState<'ai' | 'manual'>(initialTemplateId ? 'manual' : 'ai');
  const [title, setTitle] = useState('');
  const [instructions, setInstructions] = useState('');
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [numHeadings, setNumHeadings] = useState(6);
  const [templateId, setTemplateId] = useState<string>(initialTemplateId || '');

  const template = templates.find((t) => t.id === templateId) || null;
  const voice = voices.find((v) => v.id === voiceId) || null;
  const numbered = useMemo(
    () => (template ? numberHeadings(template.headings) : []),
    [template],
  );

  const submit = () => {
    onSubmit({ mode, title: title.trim(), instructions: instructions.trim(), voiceId, numHeadings, template });
  };

  return (
    <div className="brief-modal-overlay" onClick={onClose}>
      <div className="brief-modal bc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">New brief</div>
            <div className="brief-modal-sub">
              Generate an outline with AI, or start from your own headings.
            </div>
          </div>
          <button className="brief-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bc-modal-body">
          <div className="bc-mode-toggle" role="tablist">
            <button
              role="tab"
              aria-selected={mode === 'ai'}
              className={mode === 'ai' ? 'bc-mode-on' : ''}
              onClick={() => setMode('ai')}
            >
              Generate using AI
            </button>
            <button
              role="tab"
              aria-selected={mode === 'manual'}
              className={mode === 'manual' ? 'bc-mode-on' : ''}
              onClick={() => setMode('manual')}
            >
              Manual
            </button>
          </div>

          <label className="brief-label" htmlFor="bc-new-title">
            Title
          </label>
          <textarea
            id="bc-new-title"
            className="brief-textarea bc-title-input"
            rows={2}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Enter your brief title here"
          />

          {mode === 'ai' ? (
            <>
              <label className="brief-label brief-label-spaced" htmlFor="bc-new-instructions">
                Instructions <span className="brief-label-hint">(optional — guides the headings)</span>
              </label>
              <textarea
                id="bc-new-instructions"
                className="brief-textarea brief-textarea-sm"
                rows={2}
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="e.g. focus on East Africa, prioritise RCTs since 2018, structure around outcomes"
              />
              <div className="bc-field-row">
                <div className="bc-field">
                  <label className="brief-label brief-label-spaced" htmlFor="bc-new-voice">
                    Voice &amp; tone profile
                  </label>
                  <select
                    id="bc-new-voice"
                    className="bc-select"
                    value={voiceId || ''}
                    onChange={(e) => setVoiceId(e.target.value || null)}
                  >
                    <option value="">No voice profile</option>
                    {voices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="bc-field bc-field-num">
                  <label className="brief-label brief-label-spaced" htmlFor="bc-new-headings">
                    Sections
                  </label>
                  <input
                    id="bc-new-headings"
                    className="brief-number"
                    type="number"
                    min={2}
                    max={12}
                    value={numHeadings}
                    onChange={(e) => setNumHeadings(Number(e.target.value) || 6)}
                  />
                </div>
              </div>
              {voice && <div className="bc-hint">{voice.instructions.slice(0, 160)}</div>}
            </>
          ) : (
            <>
              <label className="brief-label brief-label-spaced" htmlFor="bc-new-template">
                Template
              </label>
              <select
                id="bc-new-template"
                className="bc-select"
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
              >
                <option value="">No template — blank outline</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
              <div className="bc-template-preview">
                <div className="bc-kicker">
                  {template ? "Headings you'll start with" : "You'll add headings yourself"}
                </div>
                {template ? (
                  numbered.map((h, i) => (
                    <div key={i} className={`bc-heading-row${h.sub ? ' bc-heading-sub' : ''}`}>
                      <span className="bc-heading-num">{h.num}</span>
                      <span>{h.title}</span>
                    </div>
                  ))
                ) : (
                  <div className="bc-hint">
                    The brief starts empty — add each heading in the contents panel as you go.
                  </div>
                )}
              </div>
            </>
          )}

          <div className="bc-modal-actions">
            <button className="brief-btn brief-btn-primary" onClick={submit} disabled={!title.trim() && mode === 'ai'}>
              {mode === 'ai' ? <IconSparkle size={15} /> : <IconPlus />}
              {mode === 'ai' ? 'Generate outline' : 'Create brief'}
            </button>
            <button className="brief-btn brief-btn-secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Template editor (new template, or save-from-brief)
// ---------------------------------------------------------------------------

export interface TemplateDraft {
  fromBrief: boolean;
  name: string;
  description: string;
  headings: BriefTemplateHeading[];
  withText: boolean;
}

export const BriefTemplateModal: React.FC<{
  draft: TemplateDraft;
  onSave: (draft: TemplateDraft) => Promise<void>;
  onClose: () => void;
}> = ({ draft: initial, onSave, onClose }) => {
  const [draft, setDraft] = useState<TemplateDraft>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const numbered = useMemo(() => numberHeadings(draft.headings), [draft.headings]);

  const patchHeading = (i: number, title: string) =>
    setDraft((d) => ({
      ...d,
      headings: d.headings.map((h, j) => (j === i ? { ...h, title } : h)),
    }));

  const addSub = (i: number) =>
    setDraft((d) => {
      const list = [...d.headings];
      let at = i + 1;
      while (at < list.length && list[at].sub) at += 1;
      list.splice(at, 0, { title: '', sub: true });
      return { ...d, headings: list };
    });

  const removeHeading = (i: number) =>
    setDraft((d) => ({ ...d, headings: d.headings.filter((_, j) => j !== i) }));

  const save = async () => {
    const headings = draft.headings
      .map((h) => ({ ...h, title: h.title.trim() }))
      .filter((h) => h.title);
    if (!draft.name.trim() || !headings.length) return;
    setBusy(true);
    setError(null);
    try {
      await onSave({ ...draft, headings });
    } catch (e) {
      setError(errMessage(e, 'Could not save the template.'));
      setBusy(false);
    }
  };

  return (
    <div className="brief-modal-overlay" onClick={onClose}>
      <div className="brief-modal bc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">
              {draft.fromBrief ? 'Save brief as template' : 'New template'}
            </div>
            <div className="brief-modal-sub">
              Templates save the headings so the next brief starts structured.
            </div>
          </div>
          <button className="brief-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bc-modal-body">
          {error && <div className="brief-error">{error}</div>}
          <label className="brief-label" htmlFor="bc-tpl-name">
            Template name
          </label>
          <input
            id="bc-tpl-name"
            className="bc-input"
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            placeholder="e.g. Standard evaluation synthesis"
          />
          <label className="brief-label brief-label-spaced" htmlFor="bc-tpl-desc">
            Description
          </label>
          <input
            id="bc-tpl-desc"
            className="bc-input"
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            placeholder="When to reach for this template"
          />

          {draft.fromBrief && (
            <div className="bc-inline-panel">
              <div className="bc-inline-panel-row">
                <span className="bc-inline-panel-title">Include section text</span>
                <button
                  role="switch"
                  aria-checked={draft.withText}
                  className={`brief-switch${draft.withText ? ' brief-switch-on' : ''}`}
                  onClick={() => setDraft((d) => ({ ...d, withText: !d.withText }))}
                >
                  <span className="brief-switch-thumb" />
                </button>
              </div>
              <div className="bc-hint">
                {draft.withText
                  ? 'The researched text is saved with each heading, so new briefs start from this draft.'
                  : 'Only the headings are saved — new briefs start empty under each one.'}
              </div>
            </div>
          )}

          <div className="bc-kicker bc-kicker-spaced">Headings</div>
          <div className="bc-heading-list">
            {draft.headings.map((h, i) => (
              <div key={i} className={`bc-heading-edit${h.sub ? ' bc-heading-sub' : ''}`}>
                <span className="bc-heading-num">{numbered[i].num}.</span>
                <input
                  className="bc-input"
                  value={h.title}
                  onChange={(e) => patchHeading(i, e.target.value)}
                  placeholder={h.sub ? 'Sub-heading name' : 'Heading name'}
                  aria-label={h.sub ? 'Sub-heading name' : 'Heading name'}
                />
                <button
                  className="bc-icon-btn"
                  title="Add a sub-heading"
                  aria-label="Add a sub-heading"
                  onClick={() => addSub(i)}
                >
                  <IconPlus size={13} />
                </button>
                <button
                  className="bc-icon-btn bc-icon-danger"
                  title="Remove heading"
                  aria-label="Remove heading"
                  onClick={() => removeHeading(i)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <button
            className="bc-add-dashed"
            onClick={() => setDraft((d) => ({ ...d, headings: [...d.headings, { title: '', sub: false }] }))}
          >
            <IconPlus size={14} /> Add heading
          </button>

          <div className="bc-modal-actions">
            <button
              className="brief-btn brief-btn-primary"
              onClick={() => void save()}
              disabled={busy || !draft.name.trim()}
            >
              Save template
            </button>
            <button className="brief-btn brief-btn-secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Voice & tone profile editor
// ---------------------------------------------------------------------------

export interface VoiceDraft {
  id: string | null;
  name: string;
  description: string;
  instructions: string;
}

export const BriefVoiceModal: React.FC<{
  draft: VoiceDraft;
  onSave: (draft: VoiceDraft) => Promise<void>;
  onDelete: ((id: string) => Promise<void>) | null;
  onClose: () => void;
}> = ({ draft: initial, onSave, onDelete, onClose }) => {
  const [draft, setDraft] = useState<VoiceDraft>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<void>, fallback: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errMessage(e, fallback));
      setBusy(false);
    }
  };

  return (
    <div className="brief-modal-overlay" onClick={onClose}>
      <div className="brief-modal bc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">
              {draft.id ? 'Edit voice & tone profile' : 'New voice & tone profile'}
            </div>
            <div className="brief-modal-sub">
              Instructions are applied when each section is written.
            </div>
          </div>
          <button className="brief-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bc-modal-body">
          {error && <div className="brief-error">{error}</div>}
          <label className="brief-label" htmlFor="bc-voice-name">
            Name
          </label>
          <input
            id="bc-voice-name"
            className="bc-input"
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            placeholder="e.g. Donor board memo"
          />
          <label className="brief-label brief-label-spaced" htmlFor="bc-voice-desc">
            Description
          </label>
          <input
            id="bc-voice-desc"
            className="bc-input"
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            placeholder="One line on when to use this profile"
          />
          <label className="brief-label brief-label-spaced" htmlFor="bc-voice-instructions">
            Style instructions
          </label>
          <textarea
            id="bc-voice-instructions"
            className="brief-textarea bc-voice-textarea"
            rows={7}
            value={draft.instructions}
            onChange={(e) => setDraft((d) => ({ ...d, instructions: e.target.value }))}
            placeholder="e.g. Write in plain English at reading level B2. Lead each section with the finding, then the evidence. Avoid agency jargon and acronyms on first use. Keep paragraphs under four sentences."
          />
          <div className="bc-modal-actions">
            <button
              className="brief-btn brief-btn-primary"
              disabled={busy || !draft.name.trim() || !draft.instructions.trim()}
              onClick={() => void run(() => onSave(draft), 'Could not save the profile.')}
            >
              Save profile
            </button>
            <button className="brief-btn brief-btn-secondary" onClick={onClose}>
              Cancel
            </button>
            {draft.id && onDelete && (
              <button
                className="bc-delete-btn"
                disabled={busy}
                onClick={() =>
                  void run(() => onDelete(draft.id as string), 'Could not delete the profile.')
                }
              >
                Delete profile
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Share (viewer-only)
// ---------------------------------------------------------------------------

const initialsOf = (name: string): string =>
  name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

export const BriefShareModal: React.FC<{
  briefId: string;
  briefTitle: string;
  onChanged?: () => void;
  onClose: () => void;
}> = ({ briefId, briefTitle, onChanged, onClose }) => {
  const [targets, setTargets] = useState<BriefShareTarget[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shareUrl = `${window.location.origin}/brief/${briefId}`;

  useEffect(() => {
    let cancelled = false;
    getBrief(briefId)
      .then((b) => {
        if (!cancelled) setTargets(b.shared_with);
      })
      .catch((e) => {
        if (!cancelled) setError(errMessage(e, 'Could not load sharing.'));
      });
    return () => {
      cancelled = true;
    };
  }, [briefId]);

  const add = useCallback(async () => {
    const target = input.trim();
    if (!target || busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await addBriefShare(briefId, target);
      setTargets(updated.shared_with);
      setInput('');
      onChanged?.();
    } catch (e) {
      setError(errMessage(e, 'Could not share the brief.'));
    } finally {
      setBusy(false);
    }
  }, [briefId, input, busy, onChanged]);

  const remove = useCallback(
    async (shareId: string) => {
      setError(null);
      try {
        await removeBriefShare(briefId, shareId);
        setTargets((prev) => prev.filter((t) => t.id !== shareId));
        onChanged?.();
      } catch (e) {
        setError(errMessage(e, 'Could not remove access.'));
      }
    },
    [briefId, onChanged],
  );

  const copy = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(shareUrl).catch(() => {});
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="brief-modal-overlay" onClick={onClose}>
      <div className="brief-modal bc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">Share “{briefTitle}”</div>
            <div className="brief-modal-sub">
              People you add can read this brief. Only you can edit it.
            </div>
          </div>
          <button className="brief-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bc-modal-body">
          {error && <div className="brief-error">{error}</div>}
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

          <label className="brief-label brief-label-spaced" htmlFor="bc-share-add">
            Add people or groups
          </label>
          <div className="bc-share-row">
            <input
              id="bc-share-add"
              className="bc-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void add();
              }}
              placeholder="name@org.org or group name"
            />
            <button className="brief-btn brief-btn-primary" disabled={busy} onClick={() => void add()}>
              Add
            </button>
          </div>

          <div className="bc-share-list">
            {targets.map((t) => (
              <div key={t.id} className="bc-share-item">
                <span className="bc-avatar">{initialsOf(t.name)}</span>
                <div className="bc-share-item-main">
                  <div className="bc-share-item-name">{t.name}</div>
                  <div className="bc-share-item-kind">{t.kind}</div>
                </div>
                <span className="bc-viewer-chip">Viewer</span>
                <button
                  className="bc-icon-btn bc-icon-danger"
                  title="Remove access"
                  aria-label="Remove access"
                  onClick={() => void remove(t.id)}
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
