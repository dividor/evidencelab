import configJson from '../../config.json';

/**
 * Section length target for briefs.
 *
 * A brief (or a single section) can ask for about N words per section. The
 * target is enforced three ways: the backend prompt asks for that length, the
 * token ceiling is raised to fit it, and — because models only approximate a
 * word count — a finished section that overshoots by more than `tolerance` is
 * condensed with an AI edit. The presets, bounds and tolerance come from
 * config.json (application.brief.target_words), never from code.
 */
export interface BriefLengthPreset {
  label: string;
  words: number;
}

export interface BriefLengthConfig {
  presets: BriefLengthPreset[];
  min: number;
  max: number;
  // Fraction over the target a finished section may run before it is condensed.
  tolerance: number;
}

const configured = (configJson as { application: { brief?: { target_words?: BriefLengthConfig } } })
  .application.brief?.target_words;
if (!configured) {
  throw new Error('config.json is missing application.brief.target_words');
}
export const BRIEF_LENGTH: BriefLengthConfig = configured;

const CITATION_MARKER_RE = /\[\d+(?:,\s*\d+)*\]/g;
const MARKDOWN_SYNTAX_RE = /[#*_`>|]+/g;

/** Words of prose in a section: inline [n] citation markers and markdown
 *  syntax are not words. A word is any run of characters with at least one
 *  letter or digit. */
export const countWords = (markdown: string): number =>
  (markdown || '')
    .replace(CITATION_MARKER_RE, ' ')
    .replace(MARKDOWN_SYNTAX_RE, ' ')
    .split(/\s+/)
    .filter((token) => /[\p{L}\p{N}]/u.test(token)).length;

/** The most words a section may run before it is condensed. */
export const maxWordsFor = (target: number, tolerance: number = BRIEF_LENGTH.tolerance): number =>
  Math.round(target * (1 + tolerance));

/** True when a section of `words` words overshoots `target` by more than the
 *  tolerance. No target means nothing to enforce. */
export const exceedsTarget = (
  words: number,
  target: number | null | undefined,
  tolerance: number = BRIEF_LENGTH.tolerance,
): boolean => !!target && words > maxWordsFor(target, tolerance);

/** Clamp a user-entered target to the configured bounds. */
export const clampTargetWords = (value: number): number =>
  Math.min(BRIEF_LENGTH.max, Math.max(BRIEF_LENGTH.min, Math.round(value)));

/** The AI-edit instruction that condenses an over-length section to its
 *  target. Citations must survive: the section's sources are unchanged. */
export const buildCondenseInstruction = (target: number, current: number): string =>
  `Condense this section to approximately ${target} words (it is currently about ${current} words). ` +
  'Keep every [n] citation marker attached to the claim it supports, keep the strongest and ' +
  'best-cited evidence, and cut the weakest material rather than compressing every point into a fragment.';

/** Label for a target, e.g. "Standard (~350 words)" or "~200 words". */
export const describeTarget = (target: number | null | undefined): string => {
  if (!target) return 'No target';
  const preset = BRIEF_LENGTH.presets.find((entry) => entry.words === target);
  return preset ? `${preset.label} (~${target} words)` : `~${target} words`;
};
