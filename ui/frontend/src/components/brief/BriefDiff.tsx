import React, { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Rendered diff of two markdown strings (old → new) for the Brief "show
// changes" view after an Edit/Update. Lines are diffed first (LCS) so whole
// added/removed blocks render as tinted markdown; a removed-then-added run is
// word-diffed and the add/del runs are tagged with private-use sentinel
// characters that survive markdown parsing, then wrapped in <ins>/<del> at
// render time. Self-contained so no new dependency.

type SegType = 'same' | 'add' | 'del';
interface Seg {
  type: SegType;
  text: string;
}

// Sentinels marking add/del runs inside a changed block's markdown. Private-use
// codepoints never occur in real content and pass through remark as plain text.
export const MARK_ADD_OPEN = '\uE000';
export const MARK_ADD_CLOSE = '\uE001';
export const MARK_DEL_OPEN = '\uE002';
export const MARK_DEL_CLOSE = '\uE003';

// Core LCS diff over token arrays; emits one op per token (unmerged).
const lcsOps = (a: string[], b: string[]): Seg[] => {
  const n = a.length;
  const m = b.length;
  // LCS length table (row-major, n+1 x m+1).
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops: Seg[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: 'same', text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: 'del', text: a[i] });
      i += 1;
    } else {
      ops.push({ type: 'add', text: b[j] });
      j += 1;
    }
  }
  while (i < n) ops.push({ type: 'del', text: a[i++] });
  while (j < m) ops.push({ type: 'add', text: b[j++] });
  return ops;
};

// Merge adjacent ops of the same type into contiguous segments.
const mergeOps = (ops: Seg[]): Seg[] => {
  const segs: Seg[] = [];
  ops.forEach((op) => {
    const last = segs[segs.length - 1];
    if (last && last.type === op.type) last.text += op.text;
    else segs.push({ ...op });
  });
  return segs;
};

// Split into word + whitespace tokens so re-joined output preserves spacing.
const tokenize = (s: string): string[] => s.split(/(\s+)/).filter((t) => t.length > 0);

export const diffWords = (oldText: string, newText: string): Seg[] =>
  mergeOps(lcsOps(tokenize(oldText), tokenize(newText)));

// Wrap an add/del segment in sentinels, re-opening after every newline so a
// marker pair never spans a markdown block boundary.
const markSegment = (text: string, open: string, close: string): string =>
  text
    .split('\n')
    .map((piece) => (piece.trim() ? `${open}${piece}${close}` : piece))
    .join('\n');

// Word-diff a changed old→new block into one markdown string with sentinels.
const mergeChanged = (oldText: string, newText: string): string =>
  diffWords(oldText, newText)
    .map((s) => {
      if (s.type === 'same') return s.text;
      return s.type === 'add'
        ? markSegment(s.text, MARK_ADD_OPEN, MARK_ADD_CLOSE)
        : markSegment(s.text, MARK_DEL_OPEN, MARK_DEL_CLOSE);
    })
    .join('');

export type DiffBlockType = 'same' | 'add' | 'del' | 'changed';
export interface DiffBlock {
  type: DiffBlockType;
  markdown: string;
}

/** Line-level diff grouped into renderable markdown blocks. */
export const diffBlocks = (oldText: string, newText: string): DiffBlock[] => {
  const ops = lcsOps(oldText.split('\n'), newText.split('\n'));
  const blocks: DiffBlock[] = [];
  let i = 0;
  const takeRun = (type: SegType): string[] => {
    const run: string[] = [];
    while (i < ops.length && ops[i].type === type) run.push(ops[i++].text);
    return run;
  };
  while (i < ops.length) {
    const type = ops[i].type;
    const run = takeRun(type);
    if (type === 'del') {
      // A removal immediately followed by an addition is one changed block.
      const addRun = takeRun('add');
      if (addRun.length) {
        blocks.push({ type: 'changed', markdown: mergeChanged(run.join('\n'), addRun.join('\n')) });
      } else {
        blocks.push({ type: 'del', markdown: run.join('\n') });
      }
    } else {
      blocks.push({ type, markdown: run.join('\n') });
    }
  }
  return blocks;
};

// ---- rendering ----

const MARKER_SPLIT = /([\uE000-\uE003])/;
type Mode = 'same' | 'add' | 'del';

const wrapNode = (node: React.ReactNode, mode: Mode, key: React.Key): React.ReactNode => {
  if (mode === 'add') {
    return (
      <ins key={key} className="brief-diff-add">
        {node}
      </ins>
    );
  }
  if (mode === 'del') {
    return (
      <del key={key} className="brief-diff-del">
        {node}
      </del>
    );
  }
  return <React.Fragment key={key}>{node}</React.Fragment>;
};

// Walk a node's children in order, toggling add/del mode on sentinel characters
// and wrapping the runs in <ins>/<del>. Non-string children (e.g. <strong>)
// inherit the mode active where they appear.
const renderWithMarkers = (children: React.ReactNode): React.ReactNode => {
  let mode: Mode = 'same';
  const out: React.ReactNode[] = [];
  let k = 0;
  React.Children.forEach(children, (child) => {
    if (typeof child !== 'string') {
      out.push(wrapNode(child, mode, `n${k++}`));
      return;
    }
    child.split(MARKER_SPLIT).forEach((part) => {
      if (part === MARK_ADD_OPEN) mode = 'add';
      else if (part === MARK_DEL_OPEN) mode = 'del';
      else if (part === MARK_ADD_CLOSE || part === MARK_DEL_CLOSE) mode = 'same';
      else if (part) out.push(wrapNode(part, mode, `t${k++}`));
    });
  });
  return <>{out}</>;
};

const marked =
  (Tag: string) =>
  ({ children, ...props }: any) =>
    React.createElement(Tag, props, renderWithMarkers(children));

const DIFF_COMPONENTS = {
  p: marked('p'),
  li: marked('li'),
  em: marked('em'),
  strong: marked('strong'),
  h1: marked('h1'),
  h2: marked('h2'),
  h3: marked('h3'),
  h4: marked('h4'),
  h5: marked('h5'),
  h6: marked('h6'),
};

const BLOCK_CLASS: Record<DiffBlockType, string> = {
  same: '',
  changed: '',
  add: ' brief-diff-block-add',
  del: ' brief-diff-block-del',
};

// Old and new drafts can encode the same quote differently (HTML entity vs
// straight vs curly) — e.g. an older draft has `&#34;`/`"` while a fresh revise
// has `"`. They render identically, so treat them as equal to avoid a diff full
// of meaningless quote-only "changes".
const normalizeQuotes = (s: string): string =>
  s
    .replace(/&#34;|&quot;/g, '"')
    .replace(/&#39;|&apos;|&#8217;|&#8216;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/[‘’‚‛]/g, "'")
    .replace(/[“”„‟]/g, '"');

export const BriefDiff: React.FC<{ oldText: string; newText: string }> = ({ oldText, newText }) => {
  const blocks = useMemo(
    () => diffBlocks(normalizeQuotes(oldText || ''), normalizeQuotes(newText || '')),
    [oldText, newText],
  );
  return (
    <div className="brief-diff">
      {blocks.map((b, idx) =>
        b.markdown.trim() ? (
          <div key={idx} className={`brief-diff-block${BLOCK_CLASS[b.type]}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={DIFF_COMPONENTS}>
              {b.markdown}
            </ReactMarkdown>
          </div>
        ) : null,
      )}
    </div>
  );
};
