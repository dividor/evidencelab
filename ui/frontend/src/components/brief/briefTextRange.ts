// Locating stored prose in a rendered section, and highlighting it.
//
// A comment anchor and a Fact Checker passage are both stored as text, while
// the section on screen is markdown rendered to DOM. Rather than thread them
// through the markdown renderer, the rendered output is searched afterwards
// and the match wrapped in highlight spans. The search is tolerant of what
// rendering changes: runs of whitespace (markdown wraps lines), and the
// space a citation badge leaves in front of a full stop ("A fact [1]." is
// stored by the citation check as "A fact.").
//
// The DOM is React's. A highlight must never move or copy an element React
// rendered (a citation badge, a paragraph), or React keeps updating the
// original while the reader sees the copy. So a match is wrapped one text
// node at a time: each text node's matched part is split off and wrapped in
// its own span, and elements stay exactly where React put them.

export interface TextRangeOptions {
  // Elements whose text is not part of the prose (citation badges, earlier
  // highlights of another kind): skipped when matching and never wrapped.
  skip?: string;
}

// Where one block of prose ends and the next begins; a match never spans two.
const BLOCK_SELECTOR = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, pre, td, th, div';

/** Text nodes of `root`, skipping anything under an element matching `skip`. */
export const textNodesOf = (root: HTMLElement, skip?: string): Text[] => {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      skip && node.parentElement?.closest(skip) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const out: Text[] = [];
  let n = walker.nextNode();
  while (n) {
    out.push(n as Text);
    n = walker.nextNode();
  }
  return out;
};

const PUNCTUATION = /[.,;:!?]/;

/**
 * `raw` with runs of whitespace collapsed to one space and whitespace before
 * punctuation dropped, plus the index in `raw` of every kept character, so a
 * match in the normalised text maps back to the original.
 */
export const normaliseText = (raw: string): { text: string; map: number[] } => {
  let text = '';
  const map: number[] = [];
  let i = 0;
  while (i < raw.length) {
    if (!/\s/.test(raw[i])) {
      text += raw[i];
      map.push(i);
      i += 1;
      continue;
    }
    let j = i;
    while (j < raw.length && /\s/.test(raw[j])) j += 1;
    const next = j < raw.length ? raw[j] : '';
    if (text && next && !PUNCTUATION.test(next)) {
      text += ' ';
      map.push(i);
    }
    i = j;
  }
  return { text, map };
};

const blockOf = (node: Text): Element | null => node.parentElement?.closest(BLOCK_SELECTOR) ?? null;

/**
 * Locate `quote` across the element's text nodes and return a Range spanning
 * it, or null when the prose no longer contains it. The range starts and
 * ends inside text nodes of one block.
 */
export const rangeForText = (
  root: HTMLElement,
  quote: string,
  options: TextRangeOptions = {},
): Range | null => {
  const nodes = textNodesOf(root, options.skip);
  if (!nodes.length) return null;
  // Concatenate, remembering where each node starts, so an index in the joined
  // string maps back to (node, offset). A line break separates blocks, so a
  // sentence cannot match across the end of a paragraph.
  let joined = '';
  const starts: number[] = [];
  nodes.forEach((n, i) => {
    if (i > 0 && blockOf(n) !== blockOf(nodes[i - 1])) joined += '\n';
    starts.push(joined.length);
    joined += n.data;
  });
  const needle = normaliseText(quote).text.trim();
  if (!needle) return null;
  const hay = normaliseText(joined);
  const at = hay.text.indexOf(needle);
  if (at < 0) return null;
  const startRaw = hay.map[at];
  const endRaw = hay.map[at + needle.length - 1] + 1;

  // The node holding `index`; for the end boundary, the node holding the
  // character before it, so a match ending at a node's end stays in that
  // node rather than at offset 0 of the next.
  const locate = (index: number, end: boolean): { node: Text; offset: number } | null => {
    for (let i = nodes.length - 1; i >= 0; i--) {
      if (end ? starts[i] < index : starts[i] <= index) {
        return { node: nodes[i], offset: index - starts[i] };
      }
    }
    return null;
  };
  const from = locate(startRaw, false);
  const to = locate(endRaw, true);
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

/**
 * Highlight `range`: the matched part of every text node in it (those under
 * `skip` left alone) is wrapped in its own span from `makeSpan`. Elements are
 * never moved or copied. Returns the spans, in document order; empty when
 * nothing could be wrapped.
 */
export const wrapRange = (
  range: Range,
  makeSpan: () => HTMLElement,
  skip?: string,
): HTMLElement[] => {
  const root = range.commonAncestorContainer;
  const scope = root instanceof HTMLElement ? root : root.parentElement;
  if (!scope) return [];
  const spans: HTMLElement[] = [];
  textNodesOf(scope, skip).forEach((node) => {
    if (!range.intersectsNode(node)) return;
    const start = node === range.startContainer ? range.startOffset : 0;
    const end = node === range.endContainer ? range.endOffset : node.data.length;
    if (end <= start) return;
    // Split the matched part off so the rest of the node stays as it is.
    const piece = start > 0 ? node.splitText(start) : node;
    if (end - start < piece.data.length) piece.splitText(end - start);
    const span = makeSpan();
    piece.replaceWith(span);
    span.appendChild(piece);
    spans.push(span);
  });
  return spans;
};

/**
 * Unwrap every element matching `selector` under `root`, keeping its text.
 * Text nodes are left split rather than merged: merging would discard nodes
 * React still updates.
 */
export const unwrapAll = (root: HTMLElement, selector: string): void => {
  root.querySelectorAll(selector).forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
  });
};
