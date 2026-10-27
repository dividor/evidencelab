import React from 'react';
import { VoiceProfile } from './briefTypes';

/**
 * A voice & tone profile picker. A brief, section or template can name a
 * profile the user cannot see any more (its owner stopped sharing it, or
 * deleted it). That id is kept and shown as unavailable rather than silently
 * replaced, because nothing is applied for it: the section is written without
 * a voice until the user picks another one.
 */

export const UNAVAILABLE_VOICE_LABEL = 'Unavailable voice & tone profile';

/** True when `id` names a profile that is not in the user's list. */
export const isVoiceUnavailable = (
  id: string | null | undefined,
  voices: VoiceProfile[],
): boolean => !!id && !voices.some((v) => v.id === id);

/** Option label: shared profiles say whose they are. */
export const voiceOptionLabel = (voice: VoiceProfile): string =>
  voice.can_edit || !voice.owner_name ? voice.name : `${voice.name} — shared by ${voice.owner_name}`;

// What the "Use brief default" choice resolves to, for its label.
export const briefDefaultSuffix = (briefVoiceId: string | null, briefVoice: VoiceProfile | null): string => {
  if (briefVoice) return ` — ${briefVoice.name}`;
  return briefVoiceId ? ' — unavailable' : '';
};

// The line under the voice picker: the style that will actually be applied.
// A profile the user can no longer see is applied as nothing, and says so.
export const voiceHint = (
  sectionVoiceId: string | null | undefined,
  ownVoice: VoiceProfile | null,
  briefVoiceId: string | null,
  briefVoice: VoiceProfile | null,
): string => {
  const unavailable =
    'That voice & tone profile is no longer shared with you or was deleted, so this section is written without one. Pick another profile.';
  if (sectionVoiceId) return ownVoice ? ownVoice.instructions.slice(0, 150) : unavailable;
  if (briefVoice) return `Inherits the brief profile — ${briefVoice.instructions.slice(0, 120)}`;
  return briefVoiceId ? unavailable : 'No voice profile applied';
};

export const BriefVoiceSelect: React.FC<{
  value: string | null | undefined;
  voices: VoiceProfile[];
  onChange: (id: string | null) => void;
  // Label of the "no profile" choice, e.g. "No voice profile" or "Use brief default".
  emptyLabel: string;
  id?: string;
  ariaLabel?: string;
  className?: string;
}> = ({ value, voices, onChange, emptyLabel, id, ariaLabel, className }) => (
  <select
    id={id}
    aria-label={ariaLabel}
    className={className || 'bc-select'}
    value={value || ''}
    onChange={(e) => onChange(e.target.value || null)}
  >
    <option value="">{emptyLabel}</option>
    {isVoiceUnavailable(value, voices) && (
      <option value={value || ''} disabled>
        {UNAVAILABLE_VOICE_LABEL}
      </option>
    )}
    {voices.map((v) => (
      <option key={v.id} value={v.id}>
        {voiceOptionLabel(v)}
      </option>
    ))}
  </select>
);
