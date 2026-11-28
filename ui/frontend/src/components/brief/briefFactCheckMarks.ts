// Paints the Fact Checker's passages into a rendered section.
//
// The API gives each judged passage as plain prose (citation markers and
// inline markdown removed: a bold claim arrives without its `**`), while the
// section on screen is markdown rendered to DOM with citation badges
// inline. The rendered output is searched with the badges skipped (see
// briefTextRange) and each located passage is wrapped in a mark that carries
// its verdict, so the reader sees the judge's flags in place and can select
// a claim to inspect its assessment.

import type { BriefFactCheckMark } from '../../types/testing';
import { rangeForText, unwrapAll, wrapRange } from './briefTextRange';

export const FACT_MARK_CLASS = 'brief-fact-mark';
export const FACT_ID_ATTR = 'data-fact-id';

// Inline citation badges and comment bubbles are not prose; an earlier
// fact mark is skipped so a sentence that appears twice is found again.
const SKIP = `.citation-group, .brief-comment-bubble, .${FACT_MARK_CLASS}`;

/** Remove previously painted marks, restoring the original text. */
export const clearFactMarks = (root: HTMLElement): void => {
  root.querySelectorAll('.brief-fact-claim-number').forEach(button => button.remove());
  unwrapAll(root, `.${FACT_MARK_CLASS}`);
};

/** True when every one of `marks` is painted in `root`. */
export const allPainted = (root: HTMLElement, marks: BriefFactCheckMark[]): boolean =>
  marks.every((mark) => root.querySelector(`[${FACT_ID_ATTR}="${mark.passage_id}"]`));

/**
 * Paint `marks` into `root`: each passage becomes one span per text node it
 * covers (see briefTextRange). Returns the ids of the passages that could
 * not be located in the rendered prose.
 */
export const paintFactMarks = (root: HTMLElement, marks: BriefFactCheckMark[]): number[] => {
  clearFactMarks(root);
  const missing: number[] = [];
  marks.forEach((mark) => {
    const range = rangeForText(root, mark.passage, { skip: SKIP });
    if (!range) {
      missing.push(mark.passage_id);
      return;
    }
    const spans = wrapRange(
      range,
      () => {
        const span = document.createElement('span');
        span.className = `${FACT_MARK_CLASS} ${FACT_MARK_CLASS}-${mark.verdict}`;
        span.setAttribute(FACT_ID_ATTR, String(mark.passage_id));
        return span;
      },
      SKIP,
    );
    if (!spans.length) {
      missing.push(mark.passage_id);
      return;
    }
    // One label for the passage, on its first span, for assistive technology.
    if (mark.grade) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'brief-fact-claim-number';
      button.textContent = `Claim ${mark.grade.claim}`;
      button.setAttribute('aria-haspopup', 'dialog');
      spans[0].prepend(button);
    } else {
      spans[0].tabIndex = 0;
      spans[0].setAttribute('role', 'button');
      spans[0].onkeydown = event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          spans[0].click();
        }
      };
    }
    spans[0].setAttribute('aria-label', `${mark.verdict_label}: ${mark.explanation}`);
  });
  return missing;
};

/** The mark element under `target`, if the pointer is over one. */
export const factMarkAt = (target: EventTarget | null): HTMLElement | null => {
  if (!(target instanceof Element)) return null;
  return target.closest(`.${FACT_MARK_CLASS}`) as HTMLElement | null;
};
