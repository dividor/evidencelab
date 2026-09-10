import React, { useState } from 'react';
import { BRIEF_LENGTH, clampTargetWords, describeTarget } from './briefLength';

const CUSTOM = 'custom';
const NONE = 'none';
const INHERIT = 'inherit';

/**
 * Picks a section length target: a configured preset, a custom word count, or
 * no target. With `inheritLabel` set (per-section use) the first option is
 * "use the brief's target", represented by a null value.
 */
export const BriefLengthControl: React.FC<{
  value: number | null | undefined;
  onChange: (target: number | null) => void;
  id?: string;
  // Per-section override: the null value means "inherit the brief target",
  // shown with this label (e.g. "Use brief target — Standard (~350 words)").
  inheritLabel?: string;
  ariaLabel?: string;
}> = ({ value, onChange, id, inheritLabel, ariaLabel }) => {
  const target = value ?? null;
  const isPreset = target != null && BRIEF_LENGTH.presets.some((p) => p.words === target);
  const [customMode, setCustomMode] = useState(target != null && !isPreset);
  const [customText, setCustomText] = useState(target != null && !isPreset ? String(target) : '');

  const selected = customMode ? CUSTOM : target == null ? (inheritLabel ? INHERIT : NONE) : String(target);

  const handleSelect = (choice: string) => {
    if (choice === CUSTOM) {
      setCustomMode(true);
      setCustomText(target ? String(target) : '');
      return;
    }
    setCustomMode(false);
    if (choice === NONE || choice === INHERIT) onChange(null);
    else onChange(Number(choice));
  };

  const commitCustom = () => {
    const parsed = Number(customText);
    if (!customText.trim() || Number.isNaN(parsed)) return;
    const clamped = clampTargetWords(parsed);
    setCustomText(String(clamped));
    onChange(clamped);
  };

  return (
    <div className="brief-length-control">
      <select
        id={id}
        className="bc-select"
        value={selected}
        onChange={(e) => handleSelect(e.target.value)}
        aria-label={ariaLabel}
      >
        {inheritLabel ? (
          <option value={INHERIT}>{inheritLabel}</option>
        ) : (
          <option value={NONE}>No target (model decides)</option>
        )}
        {BRIEF_LENGTH.presets.map((preset) => (
          <option key={preset.words} value={String(preset.words)}>
            {describeTarget(preset.words)}
          </option>
        ))}
        <option value={CUSTOM}>Custom…</option>
      </select>
      {customMode && (
        <label className="brief-length-custom">
          <input
            type="number"
            className="brief-number"
            min={BRIEF_LENGTH.min}
            max={BRIEF_LENGTH.max}
            step={50}
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            onBlur={commitCustom}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitCustom();
            }}
            aria-label="Target words per section"
          />
          <span>words per section</span>
        </label>
      )}
    </div>
  );
};
