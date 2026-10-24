import React, { useMemo, useState } from 'react';
import { TemplatePayload } from './briefCentralApi';
import { numberHeadings } from './BriefCentralModals';
import { IconPlus } from './BriefIcons';
import { BriefLengthControl } from './BriefLengthControl';
import { BriefTemplate, BriefTemplateHeading, VoiceProfile } from './briefTypes';
import { BriefVoiceSelect } from './BriefVoiceSelect';

/**
 * The template editor: a new template, one saved from a brief, or an edit of
 * one the user owns. A template keeps its headings and, for each, the
 * research prompt, voice & tone profile and length target; plus the
 * brief-wide prompt, voice and length that a new brief starts with.
 */

const errMessage = (e: unknown, fallback: string): string =>
  e instanceof Error ? e.message : fallback;

// Same limit as a section's typed guidance and the server's template schema.
export const PROMPT_MAX_CHARS = 2000;

// A heading in the editor carries a local key so rows keep their identity
// (and open/closed state) as headings are added and removed.
export interface DraftHeading extends BriefTemplateHeading {
  key: string;
}

export interface TemplateDraft {
  // Set when editing an existing template.
  id: string | null;
  fromBrief: boolean;
  name: string;
  description: string;
  headings: DraftHeading[];
  withText: boolean;
  // Saving from a brief: keep each section's prompt, voice and length, and the
  // brief's own prompt, voice and length.
  withSettings: boolean;
  prompt: string;
  voiceId: string | null;
  targetWords: number | null;
}

let keySeq = 0;
const nextKey = (): string => {
  keySeq += 1;
  return `h${keySeq}`;
};

export const draftHeading = (h: BriefTemplateHeading): DraftHeading => ({ ...h, key: nextKey() });

export const emptyTemplateDraft = (): TemplateDraft => ({
  id: null,
  fromBrief: false,
  name: '',
  description: '',
  headings: [draftHeading({ title: '', sub: false })],
  withText: false,
  withSettings: true,
  prompt: '',
  voiceId: null,
  targetWords: null,
});

/** Editor state for an existing template. */
export const draftFromTemplate = (t: BriefTemplate): TemplateDraft => ({
  id: t.id,
  fromBrief: false,
  name: t.name,
  description: t.description || '',
  headings: t.headings.map(draftHeading),
  withText: t.with_text,
  withSettings: true,
  prompt: t.prompt || '',
  voiceId: t.voice_profile_id,
  targetWords: t.target_words,
});

const clean = (text: string | null | undefined): string | null => (text || '').trim() || null;

/** What is sent to the server, honouring the save-from-brief switches. */
export const draftToPayload = (d: TemplateDraft): TemplatePayload => {
  const keepSettings = !d.fromBrief || d.withSettings;
  return {
    name: d.name.trim(),
    description: clean(d.description),
    headings: d.headings
      .filter((h) => h.title.trim())
      .map((h) => ({
        title: h.title.trim(),
        sub: h.sub,
        text: d.withText ? h.text ?? null : null,
        prompt: keepSettings ? clean(h.prompt) : null,
        voice_profile_id: keepSettings ? h.voice_profile_id ?? null : null,
        target_words: keepSettings ? h.target_words ?? null : null,
      })),
    withText: d.withText,
    prompt: keepSettings ? clean(d.prompt) : null,
    voiceProfileId: keepSettings ? d.voiceId : null,
    targetWords: keepSettings ? d.targetWords : null,
  };
};

/** True when a heading carries a prompt, a voice or a length target. */
export const headingHasSettings = (h: BriefTemplateHeading): boolean =>
  !!(clean(h.prompt) || h.voice_profile_id || h.target_words);

const SettingsSwitch: React.FC<{
  label: string;
  hint: string;
  on: boolean;
  onToggle: () => void;
}> = ({ label, hint, on, onToggle }) => (
  <div className="bc-inline-panel">
    <div className="bc-inline-panel-row">
      <span className="bc-inline-panel-title">{label}</span>
      <button
        role="switch"
        aria-checked={on}
        aria-label={label}
        className={`brief-switch${on ? ' brief-switch-on' : ''}`}
        onClick={onToggle}
      >
        <span className="brief-switch-thumb" />
      </button>
    </div>
    <div className="bc-hint">{hint}</div>
  </div>
);

// The brief-wide prompt, voice and length a new brief starts with.
const BriefDefaults: React.FC<{
  draft: TemplateDraft;
  voices: VoiceProfile[];
  patch: (p: Partial<TemplateDraft>) => void;
}> = ({ draft, voices, patch }) => (
  <div className="bc-inline-panel">
    <div className="bc-kicker">For the whole brief</div>
    <label className="brief-label" htmlFor="bc-tpl-prompt">
      Brief prompt <span className="brief-label-hint">(optional — applied to every section)</span>
    </label>
    <textarea
      id="bc-tpl-prompt"
      className="brief-textarea brief-textarea-sm"
      rows={2}
      maxLength={PROMPT_MAX_CHARS}
      value={draft.prompt}
      onChange={(e) => patch({ prompt: e.target.value })}
      placeholder="e.g. focus on East Africa, prioritise evaluations since 2018"
    />
    <div className="bc-field-row">
      <div className="bc-field">
        <label className="brief-label brief-label-spaced" htmlFor="bc-tpl-voice">
          Voice &amp; tone profile
        </label>
        <BriefVoiceSelect
          id="bc-tpl-voice"
          value={draft.voiceId}
          voices={voices}
          onChange={(voiceId) => patch({ voiceId })}
          emptyLabel="Not set"
        />
      </div>
      <div className="bc-field">
        <label className="brief-label brief-label-spaced" htmlFor="bc-tpl-length">
          Section length
        </label>
        <BriefLengthControl
          id="bc-tpl-length"
          value={draft.targetWords}
          onChange={(targetWords) => patch({ targetWords })}
          inheritLabel="Not set"
        />
      </div>
    </div>
  </div>
);

const headingName = (h: BriefTemplateHeading): string => h.title || 'this heading';

// One heading's prompt, voice and length, shown under the heading when opened.
const HeadingSettings: React.FC<{
  heading: DraftHeading;
  voices: VoiceProfile[];
  patch: (p: Partial<BriefTemplateHeading>) => void;
}> = ({ heading, voices, patch }) => (
  <div className="bc-heading-settings">
    <label className="brief-label" htmlFor={`bc-tpl-prompt-${heading.key}`}>
      Prompt for “{headingName(heading)}”
    </label>
    <textarea
      id={`bc-tpl-prompt-${heading.key}`}
      className="brief-textarea brief-textarea-sm"
      rows={2}
      maxLength={PROMPT_MAX_CHARS}
      value={heading.prompt || ''}
      onChange={(e) => patch({ prompt: e.target.value })}
      placeholder="What to research and emphasise in this section"
    />
    <div className="bc-field-row">
      <div className="bc-field">
        <BriefVoiceSelect
          value={heading.voice_profile_id}
          voices={voices}
          onChange={(voiceId) => patch({ voice_profile_id: voiceId })}
          emptyLabel="Use brief default voice"
          ariaLabel={`Voice and tone profile for ${headingName(heading)}`}
        />
      </div>
      <div className="bc-field">
        <BriefLengthControl
          value={heading.target_words}
          onChange={(target) => patch({ target_words: target })}
          inheritLabel="Use brief length"
          ariaLabel={`Length target for ${headingName(heading)}`}
        />
      </div>
    </div>
  </div>
);

const HeadingRow: React.FC<{
  heading: DraftHeading;
  num: string;
  open: boolean;
  showSettings: boolean;
  voices: VoiceProfile[];
  onToggle: () => void;
  onPatch: (p: Partial<BriefTemplateHeading>) => void;
  onAddSub: () => void;
  onRemove: () => void;
}> = ({ heading, num, open, showSettings, voices, onToggle, onPatch, onAddSub, onRemove }) => {
  const label = heading.sub ? 'Sub-heading name' : 'Heading name';
  const set = headingHasSettings(heading);
  return (
    <div className={`bc-heading-block${heading.sub ? ' bc-heading-sub' : ''}`}>
      <div className="bc-heading-edit">
        <span className="bc-heading-num">{num}.</span>
        <input
          className="bc-input"
          value={heading.title}
          onChange={(e) => onPatch({ title: e.target.value })}
          placeholder={label}
          aria-label={label}
        />
        {showSettings && (
          <button
            className={`bc-prompt-toggle${set ? ' bc-prompt-toggle-set' : ''}`}
            aria-expanded={open}
            title="Prompt, voice and length for this heading"
            onClick={onToggle}
          >
            {set ? 'Prompt ✓' : 'Prompt'}
          </button>
        )}
        <button className="bc-icon-btn" title="Add a sub-heading" aria-label="Add a sub-heading" onClick={onAddSub}>
          <IconPlus size={13} />
        </button>
        <button
          className="bc-icon-btn bc-icon-danger"
          title="Remove heading"
          aria-label="Remove heading"
          onClick={onRemove}
        >
          ×
        </button>
      </div>
      {showSettings && open && <HeadingSettings heading={heading} voices={voices} patch={onPatch} />}
    </div>
  );
};

const modalTitle = (d: TemplateDraft): string => {
  if (d.id) return 'Edit template';
  return d.fromBrief ? 'Save brief as template' : 'New template';
};

export const BriefTemplateModal: React.FC<{
  draft: TemplateDraft;
  voices: VoiceProfile[];
  onSave: (draft: TemplateDraft) => Promise<void>;
  onClose: () => void;
}> = ({ draft: initial, voices, onSave, onClose }) => {
  const [draft, setDraft] = useState<TemplateDraft>(initial);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const numbered = useMemo(() => numberHeadings(draft.headings), [draft.headings]);
  const showSettings = !draft.fromBrief || draft.withSettings;

  const patch = (p: Partial<TemplateDraft>) => setDraft((d) => ({ ...d, ...p }));
  const patchHeading = (key: string, p: Partial<BriefTemplateHeading>) =>
    setDraft((d) => ({ ...d, headings: d.headings.map((h) => (h.key === key ? { ...h, ...p } : h)) }));
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const addSub = (i: number) =>
    setDraft((d) => {
      const list = [...d.headings];
      let at = i + 1;
      while (at < list.length && list[at].sub) at += 1;
      list.splice(at, 0, draftHeading({ title: '', sub: true }));
      return { ...d, headings: list };
    });
  const removeHeading = (key: string) =>
    setDraft((d) => ({ ...d, headings: d.headings.filter((h) => h.key !== key) }));

  const save = async () => {
    if (!draft.name.trim() || !draft.headings.some((h) => h.title.trim())) return;
    setBusy(true);
    setError(null);
    try {
      await onSave(draft);
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
            <div className="brief-modal-title">{modalTitle(draft)}</div>
            <div className="brief-modal-sub">
              Templates save the headings, with a prompt and settings for each, so the next brief starts
              structured.
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
            onChange={(e) => patch({ name: e.target.value })}
            placeholder="e.g. Standard evaluation synthesis"
          />
          <label className="brief-label brief-label-spaced" htmlFor="bc-tpl-desc">
            Description
          </label>
          <input
            id="bc-tpl-desc"
            className="bc-input"
            value={draft.description}
            onChange={(e) => patch({ description: e.target.value })}
            placeholder="When to reach for this template"
          />

          {draft.fromBrief && (
            <>
              <SettingsSwitch
                label="Include section text"
                on={draft.withText}
                onToggle={() => patch({ withText: !draft.withText })}
                hint={
                  draft.withText
                    ? 'The researched text is saved with each heading, so new briefs start from this draft.'
                    : 'Only the headings are saved — new briefs start empty under each one.'
                }
              />
              <SettingsSwitch
                label="Include prompts and settings"
                on={draft.withSettings}
                onToggle={() => patch({ withSettings: !draft.withSettings })}
                hint={
                  draft.withSettings
                    ? "Each heading keeps its section's prompt, voice & tone profile and length, and the template keeps the brief's own."
                    : 'Prompts, voices and lengths are left out.'
                }
              />
            </>
          )}

          {showSettings && <BriefDefaults draft={draft} voices={voices} patch={patch} />}

          <div className="bc-kicker bc-kicker-spaced">Headings</div>
          <div className="bc-heading-list">
            {draft.headings.map((h, i) => (
              <HeadingRow
                key={h.key}
                heading={h}
                num={numbered[i].num}
                open={open.has(h.key)}
                showSettings={showSettings}
                voices={voices}
                onToggle={() => toggle(h.key)}
                onPatch={(p) => patchHeading(h.key, p)}
                onAddSub={() => addSub(i)}
                onRemove={() => removeHeading(h.key)}
              />
            ))}
          </div>
          <button
            className="bc-add-dashed"
            onClick={() => setDraft((d) => ({ ...d, headings: [...d.headings, draftHeading({ title: '', sub: false })] }))}
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
