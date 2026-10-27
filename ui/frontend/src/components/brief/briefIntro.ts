import configJson from '../../config.json';

/**
 * Introduction sections.
 *
 * A top-level heading followed by sub-headings is written as a short
 * introduction: it frames the theme and names what the sub-sections examine,
 * but has no headings of its own and none of their detail. The research
 * request carries the sub-headings so the backend prompt applies those rules,
 * the introduction gets its own shorter length, and one that still comes back
 * with headings is re-researched. The length and the number of re-runs are
 * set in config.json (application.brief.introductions). A deployment whose
 * config.json predates the setting, or leaves out one of its values, gets
 * BRIEF_INTRO_DEFAULTS for what is missing; a value that is present but
 * invalid stops the app with an error naming it.
 */
export interface BriefIntroConfig {
  // Default length of an introduction that has no length of its own.
  target_words: number;
  // How many times an introduction that comes back with headings is
  // re-researched before it is kept, with a warning. 0 turns re-runs off.
  heading_retries: number;
}

export const BRIEF_INTRO_DEFAULTS: BriefIntroConfig = { target_words: 120, heading_retries: 1 };

const INTRO_KEY = 'application.brief.introductions';

const checkedSetting = (
  value: unknown,
  name: keyof BriefIntroConfig,
  min: number,
  fallback: number,
): number => {
  if (value === undefined) return fallback;
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min) {
    throw new Error(`config.json ${INTRO_KEY}.${name} must be a whole number of at least ${min}`);
  }
  return value;
};

/** The introduction settings from config.json, with the defaults for any
 *  that are not set. */
export const resolveIntroConfig = (raw: unknown): BriefIntroConfig => {
  if (raw === undefined) return { ...BRIEF_INTRO_DEFAULTS };
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error(`config.json ${INTRO_KEY} must be an object`);
  }
  const settings = raw as Record<string, unknown>;
  return {
    target_words: checkedSetting(settings.target_words, 'target_words', 1, BRIEF_INTRO_DEFAULTS.target_words),
    heading_retries: checkedSetting(
      settings.heading_retries,
      'heading_retries',
      0,
      BRIEF_INTRO_DEFAULTS.heading_retries,
    ),
  };
};

export const BRIEF_INTRO: BriefIntroConfig = resolveIntroConfig(
  (configJson as { application: { brief?: { introductions?: unknown } } }).application.brief
    ?.introductions,
);

export interface OutlineEntry {
  id: string;
  title: string;
  level: number; // 1 = section, 2 = sub-section
}

/** Titles of the sub-sections under a top-level section; [] when it has none
 *  (or is itself a sub-section). */
export const subSectionTitles = (sections: OutlineEntry[], id: string): string[] => {
  const idx = sections.findIndex((s) => s.id === id);
  if (idx < 0 || sections[idx].level === 2) return [];
  const subs: string[] = [];
  for (let i = idx + 1; i < sections.length && sections[i].level === 2; i++) {
    subs.push(sections[i].title);
  }
  return subs;
};

/**
 * The length a section is written to. The section's own length always wins.
 * Otherwise an introduction uses the introduction length (never longer than
 * the brief's own target), and any other section the brief's target.
 */
export const sectionTargetWords = (
  sectionTarget: number | null | undefined,
  subSections: string[],
  briefTarget: number | null,
  introTarget: number = BRIEF_INTRO.target_words,
): number | null => {
  if (sectionTarget != null) return sectionTarget;
  if (!subSections.length) return briefTarget;
  return briefTarget != null ? Math.min(introTarget, briefTarget) : introTarget;
};

const HEADING_LINE_RE = /^#{1,6}\s+\S/;

/**
 * Heading lines a section wrote into its text. A leading heading (the model
 * often restates the section's own title, which the page already hides) does
 * not count; any other markdown heading does.
 */
export const extraHeadingLines = (markdown: string): string[] => {
  const lines = (markdown || '')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  const body = lines.length && HEADING_LINE_RE.test(lines[0]) ? lines.slice(1) : lines;
  return body.filter((l) => HEADING_LINE_RE.test(l));
};

/**
 * The order a whole-brief run researches sections in: each top-level section
 * that has sub-sections comes after them, so its introduction can see what
 * they say; everything else keeps reading order.
 */
export const researchOrder = (sections: OutlineEntry[]): string[] => {
  const order: string[] = [];
  for (let i = 0; i < sections.length; i++) {
    const s = sections[i];
    if (s.level === 2) {
      // A sub-section before any top-level heading has no introduction to wait for.
      if (!sections.slice(0, i).some((p) => p.level !== 2)) order.push(s.id);
      continue;
    }
    let j = i + 1;
    while (j < sections.length && sections[j].level === 2) {
      order.push(sections[j].id);
      j++;
    }
    order.push(s.id);
  }
  return order;
};
