import React from 'react';

// Word-level diff of two markdown strings (old → new) for the Brief "show
// changes" view after an Edit/Update. Self-contained LCS so no new dependency.

type SegType = 'same' | 'add' | 'del';
interface Seg {
  type: SegType;
  text: string;
}

// Split into word + whitespace tokens so re-joined output preserves spacing.
const tokenize = (s: string): string[] => s.split(/(\s+)/).filter((t) => t.length > 0);

export const diffWords = (oldText: string, newText: string): Seg[] => {
  const a = tokenize(oldText);
  const b = tokenize(newText);
  const n = a.length;
  const m = b.length;
  // LCS length table (row-major, n+1 x m+1).
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const segs: Seg[] = [];
  const push = (type: SegType, text: string) => {
    const last = segs[segs.length - 1];
    if (last && last.type === type) last.text += text;
    else segs.push({ type, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push('same', a[i]);
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push('del', a[i]);
      i += 1;
    } else {
      push('add', b[j]);
      j += 1;
    }
  }
  while (i < n) {
    push('del', a[i]);
    i += 1;
  }
  while (j < m) {
    push('add', b[j]);
    j += 1;
  }
  return segs;
};

export const BriefDiff: React.FC<{ oldText: string; newText: string }> = ({ oldText, newText }) => {
  const segs = diffWords(oldText || '', newText || '');
  return (
    <div className="brief-diff">
      {segs.map((s, idx) => {
        if (s.type === 'same') return <span key={idx}>{s.text}</span>;
        if (s.type === 'add')
          return (
            <ins key={idx} className="brief-diff-add">
              {s.text}
            </ins>
          );
        return (
          <del key={idx} className="brief-diff-del">
            {s.text}
          </del>
        );
      })}
    </div>
  );
};
