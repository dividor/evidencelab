// Paints commented passages into a rendered section.
//
// A comment's anchor is stored as quoted text (see briefCommentAnchors), while
// the section on screen is markdown rendered to DOM. Rather than thread the
// anchors through the markdown renderer, the rendered output is decorated
// afterwards: the passage is wrapped in a highlight and a small speech-bubble
// button is placed at its end.

export interface CommentMark {
  threadId: string;
  quote: string;
  // Unread/open vs resolved, so resolved threads can be dimmed.
  resolved: boolean;
  count: number;
}

export const MARK_CLASS = 'brief-comment-mark';
export const BUBBLE_CLASS = 'brief-comment-bubble';

/** Text nodes of `root`, skipping anything already decorated. */
const textNodesOf = (root: HTMLElement): Text[] => {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      (node.parentElement?.closest(`.${MARK_CLASS}, .${BUBBLE_CLASS}`))
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  const out: Text[] = [];
  let n = walker.nextNode();
  while (n) {
    out.push(n as Text);
    n = walker.nextNode();
  }
  return out;
};

/**
 * Locate `quote` across the element's text nodes and return a Range spanning
 * it. Whitespace in the rendered DOM can differ from the stored quote, so both
 * sides are compared with runs of whitespace collapsed.
 */
const rangeForQuote = (root: HTMLElement, quote: string): Range | null => {
  const nodes = textNodesOf(root);
  if (!nodes.length) return null;
  // Concatenate, remembering where each node starts, so an index in the joined
  // string maps back to (node, offset).
  let joined = '';
  const starts: number[] = [];
  nodes.forEach((n) => {
    starts.push(joined.length);
    joined += n.data;
  });
  const norm = (s: string): string => s.replace(/\s+/g, ' ');
  const at = norm(joined).indexOf(norm(quote).trim());
  if (at < 0) return null;
  // Map the normalised index back to the raw string by walking both together.
  let raw = 0;
  let normed = 0;
  const target = at;
  const targetEnd = at + norm(quote).trim().length;
  let startRaw = -1;
  let endRaw = -1;
  while (raw < joined.length) {
    const isSpace = /\s/.test(joined[raw]);
    const collapses = isSpace && raw > 0 && /\s/.test(joined[raw - 1]);
    if (!collapses) {
      if (normed === target && startRaw < 0) startRaw = raw;
      if (normed === targetEnd) {
        endRaw = raw;
        break;
      }
      normed += 1;
    }
    raw += 1;
  }
  if (startRaw < 0) return null;
  if (endRaw < 0) endRaw = joined.length;

  const locate = (index: number): { node: Text; offset: number } | null => {
    for (let i = nodes.length - 1; i >= 0; i--) {
      if (starts[i] <= index) return { node: nodes[i], offset: index - starts[i] };
    }
    return null;
  };
  const from = locate(startRaw);
  const to = locate(endRaw);
  if (!from || !to) return null;
  const range = document.createRange();
  try {
    range.setStart(from.node, Math.min(from.offset, from.node.data.length));
    range.setEnd(to.node, Math.min(to.offset, to.node.data.length));
  } catch {
    return null;
  }
  return range;
};

/** Remove previously painted marks, restoring the original text. */
export const clearCommentMarks = (root: HTMLElement): void => {
  root.querySelectorAll(`.${BUBBLE_CLASS}`).forEach((b) => b.remove());
  root.querySelectorAll(`.${MARK_CLASS}`).forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parent.normalize();
  });
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
    const range = rangeForQuote(root, mark.quote);
    if (!range) {
      orphaned.push(mark.threadId);
      return;
    }
    const span = document.createElement('span');
    span.className = `${MARK_CLASS}${mark.resolved ? ' brief-comment-mark-resolved' : ''}`;
    span.setAttribute('data-thread-id', mark.threadId);
    try {
      range.surroundContents(span);
    } catch {
      // The selection crosses element boundaries (e.g. part of a link); wrap
      // its extracted contents instead, which handles the partial-node case.
      try {
        span.appendChild(range.extractContents());
        range.insertNode(span);
      } catch {
        orphaned.push(mark.threadId);
        return;
      }
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
    span.after(bubble);
  });
  return orphaned;
};
