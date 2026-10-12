import React, { useMemo, useState } from 'react';
import { BriefLengthControl } from './BriefLengthControl';
import { IconPlus, IconSparkle } from './BriefIcons';
import { BriefTemplate, BriefTemplateHeading, VoiceProfile } from './briefTypes';
import { BriefVoiceSelect } from './BriefVoiceSelect';

/**
 * The Brief Central modals: New brief, voice & tone profile editor and
 * Regenerate all. The template editor is in BriefTemplateModal.tsx and the
 * Share dialog in BriefShareDialog.tsx. All reuse the `.brief-modal-*` shell
 * classes plus `.bc-*` styles from brief.css.
 */

const errMessage = (e: unknown, fallback: string): string =>
  e instanceof Error ? e.message : fallback;

// Numbering matching the brief document: 1, 1.1, 1.2, 2, … `hasPrompt` marks
// headings that carry a research prompt, for template previews.
export const numberHeadings = (
  headings: BriefTemplateHeading[],
): { num: string; title: string; sub: boolean; hasPrompt: boolean }[] => {
  let top = 0;
  let sub = 0;
  return headings.map((h) => {
    const hasPrompt = !!h.prompt;
    if (h.sub && top > 0) {
      sub += 1;
      return { num: `${top}.${sub}`, title: h.title, sub: true, hasPrompt };
    }
    top += 1;
    sub = 0;
    return { num: `${top}`, title: h.title, sub: false, hasPrompt };
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
  // Section length target in words; null = no target.
  targetWords: number | null;
  template: BriefTemplate | null;
}

export const BriefNewModal: React.FC<{
  templates: BriefTemplate[];
  voices: VoiceProfile[];
  initialTemplateId?: string | null;
  // The group's default section length, if the team set one.
  defaultTargetWords?: number | null;
  onSubmit: (args: NewBriefSubmit) => void;
  onClose: () => void;
}> = ({ templates, voices, initialTemplateId, defaultTargetWords, onSubmit, onClose }) => {
  // A template brings its brief-wide prompt, voice and length with it; the
  // user can still change them here before creating the brief.
  const initialTemplate = templates.find((t) => t.id === initialTemplateId) || null;
  const [mode, setMode] = useState<'ai' | 'manual'>(initialTemplateId ? 'manual' : 'ai');
  const [title, setTitle] = useState('');
  const [instructions, setInstructions] = useState(initialTemplate?.prompt || '');
  const [voiceId, setVoiceId] = useState<string | null>(initialTemplate?.voice_profile_id ?? null);
  const [numHeadings, setNumHeadings] = useState(6);
  const [targetWords, setTargetWords] = useState<number | null>(
    initialTemplate?.target_words ?? defaultTargetWords ?? null,
  );
  const [templateId, setTemplateId] = useState<string>(initialTemplateId || '');

  const template = templates.find((t) => t.id === templateId) || null;
  const voice = voices.find((v) => v.id === voiceId) || null;
  const numbered = useMemo(
    () => (template ? numberHeadings(template.headings) : []),
    [template],
  );

  const pickTemplate = (id: string) => {
    setTemplateId(id);
    const picked = templates.find((t) => t.id === id);
    if (!picked) return;
    setInstructions(picked.prompt || '');
    setVoiceId(picked.voice_profile_id);
    if (picked.target_words != null) setTargetWords(picked.target_words);
  };

  const submit = () => {
    onSubmit({
      mode,
      title: title.trim(),
      instructions: instructions.trim(),
      voiceId,
      numHeadings,
      targetWords,
      template,
    });
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
                  <BriefVoiceSelect
                    id="bc-new-voice"
                    value={voiceId}
                    voices={voices}
                    onChange={setVoiceId}
                    emptyLabel="No voice profile"
                  />
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
                onChange={(e) => pickTemplate(e.target.value)}
              >
                <option value="">No template — blank outline</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.can_edit || !t.owner_name ? t.name : `${t.name} — shared by ${t.owner_name}`}
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
                      {h.hasPrompt && <span className="bc-prompt-mark">prompt</span>}
                    </div>
                  ))
                ) : (
                  <div className="bc-hint">
                    The brief starts empty — add each heading in the contents panel as you go.
                  </div>
                )}
              </div>
              <label className="brief-label brief-label-spaced" htmlFor="bc-new-prompt">
                Brief prompt <span className="brief-label-hint">(optional — applied to every section)</span>
              </label>
              <textarea
                id="bc-new-prompt"
                className="brief-textarea brief-textarea-sm"
                rows={2}
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="e.g. focus on East Africa, prioritise evaluations since 2018"
              />
              <label className="brief-label brief-label-spaced" htmlFor="bc-new-manual-voice">
                Voice &amp; tone profile
              </label>
              <BriefVoiceSelect
                id="bc-new-manual-voice"
                value={voiceId}
                voices={voices}
                onChange={setVoiceId}
                emptyLabel="No voice profile"
              />
            </>
          )}

          <div className="bc-field">
            <label className="brief-label brief-label-spaced" htmlFor="bc-new-length">
              Section length
            </label>
            <BriefLengthControl id="bc-new-length" value={targetWords} onChange={setTargetWords} />
            <div className="bc-hint">
              About this many words per section. Sections that run long are condensed automatically.
            </div>
          </div>
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
// Regenerate all sections
// ---------------------------------------------------------------------------

export interface RegenAllSubmit {
  instructions: string;
  voiceId: string | null;
  // Section length target in words; null = no target.
  targetWords: number | null;
  // Clear each section's own profile so the chosen one applies document-wide.
  applyVoiceToAllSections: boolean;
}

/**
 * Confirmation for the document-wide "AI Regenerate All": every section is
 * re-researched from scratch, so the user gets a chance to steer the run with
 * guidance and a voice & tone profile before it starts.
 */
export const BriefRegenAllModal: React.FC<{
  voices: VoiceProfile[];
  briefVoiceId: string | null;
  instructions: string;
  targetWords: number | null;
  hasSectionVoices: boolean;
  onSubmit: (submit: RegenAllSubmit) => void;
  onClose: () => void;
}> = ({
  voices,
  briefVoiceId,
  instructions: initial,
  targetWords: initialTarget,
  hasSectionVoices,
  onSubmit,
  onClose,
}) => {
  const [instructions, setInstructions] = useState(initial);
  const [voiceId, setVoiceId] = useState<string | null>(briefVoiceId);
  const [targetWords, setTargetWords] = useState<number | null>(initialTarget);
  const [applyToAll, setApplyToAll] = useState(false);
  const selected = voices.find((v) => v.id === voiceId) || null;

  return (
    <div className="brief-modal-overlay" onClick={onClose}>
      <div className="brief-modal bc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">Regenerate all sections</div>
            <div className="brief-modal-sub">
              Every section is re-researched from scratch with these settings.
            </div>
          </div>
          <button className="brief-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bc-modal-body">
          <label className="brief-label" htmlFor="bc-regen-instructions">
            Instructions <span className="brief-label-hint">(optional — guides the research)</span>
          </label>
          <textarea
            id="bc-regen-instructions"
            className="brief-textarea brief-textarea-sm"
            rows={3}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="e.g. emphasise evidence since 2020, foreground cost-efficiency, flag where evidence is thin"
          />
          <label className="brief-label brief-label-spaced" htmlFor="bc-regen-voice">
            Voice &amp; tone profile
          </label>
          <BriefVoiceSelect
            id="bc-regen-voice"
            value={voiceId}
            voices={voices}
            onChange={setVoiceId}
            emptyLabel="No voice profile"
          />
          {selected && <div className="bc-voice-hint">{selected.description}</div>}
          <label className="brief-label brief-label-spaced" htmlFor="bc-regen-length">
            Section length
          </label>
          <BriefLengthControl id="bc-regen-length" value={targetWords} onChange={setTargetWords} />
          <div className="bc-hint">
            About this many words per section; sections with their own length keep it.
          </div>
          {hasSectionVoices && (
            <>
              <div className="bc-voice-hint">
                Sections with their own voice profile keep it unless you overwrite them below.
              </div>
              <label className="bc-checkbox-row">
                <input
                  type="checkbox"
                  checked={applyToAll}
                  onChange={(e) => setApplyToAll(e.target.checked)}
                />
                Apply this profile to every section
              </label>
            </>
          )}
          <div className="bc-modal-actions">
            <button
              className="brief-btn brief-btn-primary"
              onClick={() =>
                onSubmit({ instructions, voiceId, targetWords, applyVoiceToAllSections: applyToAll })
              }
            >
              <IconSparkle /> Regenerate all sections
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
