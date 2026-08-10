// Shared citation rendering for assistant/brief output: turns `[N]` markers in
// Markdown into clickable number-badge citations grouped by document, and a
// references list grouped by document. Used by the Research Assistant
// (ChatMessage) and the Brief tab so both render citations identically.

import React, { useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { SourceReference } from '../../types/api';
import { parseAndRenderSuperscripts } from '../../utils/textHighlighting';

const CITATION_REGEX = /\[(\d+(?:,\s*\d+)*)\]/g;

const parseCitationNumbers = (raw: string): number[] =>
  raw
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => !isNaN(n));

/** Extract all unique cited numbers from the response text. */
export const extractCitedNumbers = (text: string): number[] => {
  const cited = new Set<number>();
  let m: RegExpExecArray | null;
  const re = new RegExp(CITATION_REGEX.source, 'g');
  while ((m = re.exec(text)) !== null) {
    parseCitationNumbers(m[1]).forEach((n) => cited.add(n));
  }
  return Array.from(cited).sort((a, b) => a - b);
};

/**
 * Canonical form of a citing sentence used to key per-claim highlight matches:
 * citation markers and markdown decoration stripped, whitespace collapsed,
 * lowercased. Must produce identical keys at enrichment and render time.
 */
export const normalizeClaimText = (text: string): string =>
  text
    .replace(/\[(?:\d+,\s*)*\d+\]/g, '')
    .replace(/[#*_>`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();

/** The sentence surrounding a citation marker at `pos` within a text node. */
export const sentenceAround = (text: string, pos: number): string => {
  let start = 0;
  for (let i = pos - 1; i >= 0; i--) {
    if ('.!?\n'.includes(text[i])) {
      start = i + 1;
      break;
    }
  }
  let end = text.length;
  for (let i = pos; i < text.length; i++) {
    if ('.!?\n'.includes(text[i])) {
      end = i + 1;
      break;
    }
  }
  return text.slice(start, end).trim();
};

// A leading "-- h1 > h2 > h3 --" line is a heading breadcrumb embedded in the
// chunk text. Split it off so the excerpt can show it as an italic section path
// (without the -- markers) above the body.
const SECTION_BREADCRUMB_RE = /^\s*--\s*(.+?)\s*--\s*$/;

export const parseSectionBreadcrumb = (
  text: string,
): { section: string | null; body: string } => {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  while (i < lines.length && lines[i].trim() === '') i++;
  const match = i < lines.length ? SECTION_BREADCRUMB_RE.exec(lines[i].trim()) : null;
  if (match && match[1].includes(' > ')) {
    const body = lines
      .slice(i + 1)
      .join('\n')
      .replace(/^\n+/, '');
    return { section: match[1].trim(), body };
  }
  return { section: null, body: text };
};

// Expand a match to whole-word boundaries so snippets never start or end
// mid-word (the phrase matcher is fuzzy and can clip by a few characters).
export const snapToWordBounds = (
  text: string,
  start: number,
  end: number,
): { start: number; end: number } => {
  const isWordChar = (ch: string): boolean => /[\p{L}\p{N}]/u.test(ch);
  let s = Math.max(0, Math.min(start, text.length));
  let e = Math.max(s, Math.min(end, text.length));
  while (s > 0 && isWordChar(text[s - 1]) && s < text.length && isWordChar(text[s])) s--;
  while (e < text.length && e > 0 && isWordChar(text[e - 1]) && isWordChar(text[e])) e++;
  return { start: s, end: e };
};

const renderCitationExcerpt = (
  text: string,
  semanticMatches?: Array<{ start: number; end: number }>,
): React.ReactNode => {
  const { section, body } = parseSectionBreadcrumb(text);
  // LLM-highlighted excerpts show ONLY the claim-supporting span(s), separated
  // by ellipses — not the whole excerpt. Offsets are relative to the body
  // (after the breadcrumb split). Without matches, the full excerpt renders.
  const renderBody = (b: string): React.ReactNode => {
    const snippets = (semanticMatches || [])
      .map((m) => {
        const { start, end } = snapToWordBounds(b, m.start, m.end);
        return b.substring(start, end).trim();
      })
      .filter(Boolean);
    if (!snippets.length) return parseAndRenderSuperscripts(b);
    return (
      <span className="citation-hover-snippets">
        {snippets.map((s) => `“${s}”`).join(' … ')}
      </span>
    );
  };
  if (!section) return renderBody(text);
  return (
    <>
      <div className="citation-hover-section">{section}</div>
      {body.trim() && <div>{renderBody(body)}</div>}
    </>
  );
};

/**
 * Highlight matches for the specific citing sentence being hovered. Falls back
 * to the source-level matches (older briefs) when per-claim data is absent —
 * but only if there is a single claim entry, since source-level matches for a
 * multiply-cited source mix claims and mislead.
 */
const matchesForClaim = (
  source: SourceReference,
  claim: string | undefined,
): Array<{ start: number; end: number }> | undefined => {
  const entries = source.claimMatches;
  if (entries?.length) {
    if (claim) {
      const key = normalizeClaimText(claim);
      const hit = entries.find((e) => e.claim === key);
      if (hit) return hit.matches;
    }
    return entries.length === 1 ? entries[0].matches : undefined;
  }
  return source.semanticMatches;
};

const InlineCitation: React.FC<{
  num: number;
  source?: SourceReference;
  onClick?: (source: SourceReference) => void;
  claim?: string;
}> = ({ num, source, onClick, claim }) => {
  const ref = useRef<HTMLAnchorElement>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [card, setCard] = useState<{ top: number; left: number } | null>(null);

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (source && onClick) onClick(source);
  };

  const show = () => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    if (!source) return;
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    // Position below the badge, clamped so the card stays in the viewport.
    const CARD_W = 360;
    setCard({ top: r.bottom + 6, left: Math.min(r.left, window.innerWidth - CARD_W - 12) });
  };
  const scheduleHide = () => {
    hideTimer.current = setTimeout(() => setCard(null), 120);
  };

  return (
    <>
      <a
        ref={ref}
        href="#"
        className="ai-summary-citation"
        onClick={handleClick}
        onMouseEnter={show}
        onMouseLeave={scheduleHide}
      >
        {num}
      </a>
      {card &&
        source &&
        createPortal(
          <div
            className="citation-hover-card"
            style={{ top: card.top, left: card.left }}
            onMouseEnter={show}
            onMouseLeave={scheduleHide}
          >
            <div className="citation-hover-title">{source.title || `Source ${num}`}</div>
            {typeof source.page === 'number' && (
              <div className="citation-hover-meta">Page {source.page}</div>
            )}
            {source.text && (
              <div className="citation-hover-excerpt">
                {renderCitationExcerpt(source.text, matchesForClaim(source, claim))}
              </div>
            )}
          </div>,
          document.body,
        )}
    </>
  );
};

/** Split a text string on citation patterns and return mixed text + badges. */
function replaceCitations(
  text: string,
  sourceByIndex: Map<number, SourceReference>,
  onSourceClick?: (source: SourceReference) => void,
): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const re = new RegExp(CITATION_REGEX.source, 'g');
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    const claim = sentenceAround(text, match.index);
    const nums = parseCitationNumbers(match[1]);
    // Group consecutive citations by document.
    const groups: number[][] = [];
    for (const n of nums) {
      const docId = sourceByIndex.get(n)?.docId;
      const prev = groups.length > 0 ? groups[groups.length - 1] : null;
      const prevDocId = prev && sourceByIndex.get(prev[0])?.docId;
      if (prev && docId && docId === prevDocId) {
        prev.push(n);
      } else {
        groups.push([n]);
      }
    }
    parts.push(
      <span key={`cite-${match.index}`} className="citation-group">
        {groups.map((group, gi) => (
          <React.Fragment key={`g-${gi}`}>
            {gi > 0 && ' '}
            <span className="citation-doc-group">
              {group.map((n, i) => (
                <React.Fragment key={n}>
                  {i > 0 && <span>, </span>}
                  <InlineCitation
                    num={n}
                    source={sourceByIndex.get(n)}
                    onClick={onSourceClick}
                    claim={claim}
                  />
                </React.Fragment>
              ))}
            </span>
          </React.Fragment>
        ))}
      </span>,
    );
    lastIndex = re.lastIndex;
  }

  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

/** Recursively walk React children and replace citation text patterns. */
function transformChildren(
  children: React.ReactNode,
  sourceByIndex: Map<number, SourceReference>,
  onSourceClick?: (source: SourceReference) => void,
): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child !== 'string') return child;
    return replaceCitations(child, sourceByIndex, onSourceClick);
  });
}

export const CitedMarkdown: React.FC<{
  content: string;
  sources: SourceReference[];
  onSourceClick?: (source: SourceReference) => void;
}> = ({ content, sources, onSourceClick }) => {
  const sourceByIndex = useMemo(() => {
    const map = new Map<number, SourceReference>();
    sources.forEach((s) => {
      if (s.index != null) map.set(s.index, s);
    });
    return map;
  }, [sources]);

  const components = useMemo(
    () => ({
      p: ({ children, ...props }: any) => (
        <p {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</p>
      ),
      li: ({ children, ...props }: any) => (
        <li {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</li>
      ),
      strong: ({ children, ...props }: any) => (
        <strong {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</strong>
      ),
      em: ({ children, ...props }: any) => (
        <em {...props}>{transformChildren(children, sourceByIndex, onSourceClick)}</em>
      ),
    }),
    [sourceByIndex, onSourceClick],
  );

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
};

interface DocGroup {
  title: string;
  docId: string;
  indices: number[];
  page?: number;
}

/** Group cited sources by document for a references / footnotes list. */
export const groupCitedSourcesByDoc = (
  content: string,
  sources: SourceReference[],
): DocGroup[] => {
  const cited = extractCitedNumbers(content);
  const sourceByIndex = new Map<number, SourceReference>();
  sources.forEach((s) => {
    if (s.index != null) sourceByIndex.set(s.index, s);
  });
  const groupMap = new Map<string, DocGroup>();
  const order: string[] = [];
  cited.forEach((num) => {
    const src = sourceByIndex.get(num);
    if (!src) return;
    const key = src.docId || src.title;
    if (!groupMap.has(key)) {
      groupMap.set(key, { title: src.title, docId: src.docId, indices: [], page: src.page });
      order.push(key);
    }
    groupMap.get(key)!.indices.push(num);
  });
  return order.map((k) => groupMap.get(k)!);
};

const RefGroupLinks: React.FC<{
  group: DocGroup;
  sources: SourceReference[];
  onSourceClick?: (source: SourceReference) => void;
}> = ({ group, sources, onSourceClick }) => (
  <div className="ai-summary-ref-group">
    {group.title}
    {' | '}
    {group.indices.map((idx, i) => (
      <React.Fragment key={idx}>
        {i > 0 && ' '}
        <a
          href="#"
          className="ai-summary-ref-link"
          onClick={(e) => {
            e.preventDefault();
            const src = sources.find((s) => s.index === idx);
            if (src && onSourceClick) onSourceClick(src);
          }}
        >
          <span className="citation-doc-group">
            <span className="ai-summary-citation">{idx}</span>
          </span>
          {group.page ? ` p.${group.page}` : ''}
        </a>
      </React.Fragment>
    ))}
  </div>
);

/** References for one block of cited content, grouped by document. */
export const CitedReferences: React.FC<{
  content: string;
  sources: SourceReference[];
  onSourceClick?: (source: SourceReference) => void;
  collapsible?: boolean;
  labelPrefix?: string;
  className?: string;
}> = ({
  content,
  sources,
  onSourceClick,
  collapsible = true,
  labelPrefix = 'References',
  className = '',
}) => {
  const [expanded, setExpanded] = useState(!collapsible);
  const groups = useMemo(() => groupCitedSourcesByDoc(content, sources), [content, sources]);
  if (groups.length === 0) return null;

  const containerClass = className
    ? `ai-summary-references ${className}`
    : 'ai-summary-references';
  const list = (
    <div className="assistant-refs-list">
      {groups.map((group) => (
        <RefGroupLinks
          key={group.docId || group.title}
          group={group}
          sources={sources}
          onSourceClick={onSourceClick}
        />
      ))}
    </div>
  );

  if (!collapsible) return <div className={containerClass}>{list}</div>;

  return (
    <div className={containerClass}>
      <button className="assistant-refs-toggle" onClick={() => setExpanded(!expanded)}>
        <span className="assistant-refs-toggle-icon">{expanded ? '▾' : '▸'}</span>
        {labelPrefix} ({groups.length} {groups.length === 1 ? 'document' : 'documents'})
      </button>
      {expanded && list}
    </div>
  );
};
