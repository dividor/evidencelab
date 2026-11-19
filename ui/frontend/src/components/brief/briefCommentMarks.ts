// Paints commented passages into a rendered section.
//
// A comment's anchor is stored as quoted text (see briefCommentAnchors), while
// the section on screen is markdown rendered to DOM. Rather than thread the
// anchors through the markdown renderer, the rendered output is decorated
// afterwards: the passage is wrapped in a highlight and a small speech-bubble
// button is placed at its end.

import { rangeForText, unwrapAll, wrapRange } from './briefTextRange';

export interface CommentMark {
  threadId: string;
  quote: string;
  // Unread/open vs resolved, so resolved threads can be dimmed.
  resolved: boolean;
  count: number;
}

export const MARK_CLASS = 'brief-comment-mark';
export const BUBBLE_CLASS = 'brief-comment-bubble';

/** Remove previously painted marks, restoring the original text. */
export const clearCommentMarks = (root: HTMLElement): void => {
  root.querySelectorAll(`.${BUBBLE_CLASS}`).forEach((b) => b.remove());
  unwrapAll(root, `.${MARK_CLASS}`);
};

/**
 * Paint `marks` into `root`. Returns the thread ids that could not be located
 * (their passage has changed or gone), so the caller can show them as
 * unanchored in the rail rather than losing them silently.
 */
export const paintCommentMarks = (root: HTMLElement, marks: CommentMark[]): string[] => {
  clearCommentMarks(root);
  const orphaned: string[] = [];
  marks.forEach((mark) => {
    if (!mark.quote) {
      orphaned.push(mark.threadId);
      return;
    }
    // Earlier marks and bubbles are not prose, so a quote never matches
    // inside one; this is what lets the same passage be found twice.
    const range = rangeForText(root, mark.quote, { skip: `.${MARK_CLASS}, .${BUBBLE_CLASS}` });
    if (!range) {
      orphaned.push(mark.threadId);
      return;
    }
    const spans = wrapRange(
      range,
      () => {
        const span = document.createElement('span');
        span.className = `${MARK_CLASS}${mark.resolved ? ' brief-comment-mark-resolved' : ''}`;
        span.setAttribute('data-thread-id', mark.threadId);
        return span;
      },
      // Citation badges keep their own markup; the highlight skips them.
      `.citation-group, .${BUBBLE_CLASS}`,
    );
    if (!spans.length) {
      orphaned.push(mark.threadId);
      return;
    }
    const bubble = document.createElement('button');
    bubble.type = 'button';
    bubble.className = BUBBLE_CLASS;
    bubble.setAttribute('data-thread-id', mark.threadId);
    bubble.setAttribute(
      'aria-label',
      `${mark.count} comment${mark.count === 1 ? '' : 's'} on “${mark.quote.slice(0, 40)}”`,
    );
    bubble.title = 'Show this comment';
    bubble.textContent = mark.count > 1 ? String(mark.count) : '';
    spans[spans.length - 1].after(bubble);
  });
  return orphaned;
};
