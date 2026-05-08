import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import API_BASE_URL, { PDF_SEMANTIC_HIGHLIGHTS, PDF_SEARCH_SEMANTIC_CUTOFF } from '../config';
import { HighlightBox, SummaryModelConfig } from '../types/api';
import { findAllMatches, findSemanticMatches, TextMatch } from '../utils/textHighlighting';
import TocModal from './TocModal';

// PDF.js types
declare global {
  interface Window {
    pdfjsLib: any;
  }
}

const getResponsiveScale = (): number => {
  if (window.innerWidth <= 640) {
    const containerWidth = window.innerWidth - 32;
    return Math.max(0.5, Math.min(containerWidth / 600, 1.5));
  }
  return 1.5;
};

/**
 * Merge vertically sequential/adjacent highlight bboxes on the same page
 * into single larger bounding boxes. This prevents fragmented highlighting
 * when a chunk spans multiple small bboxes.
 */
const mergeSequentialHighlights = (highlights: HighlightBox[]): HighlightBox[] => {
  if (highlights.length <= 1) return highlights;

  // Group by page
  const byPage = new Map<number, HighlightBox[]>();
  for (const h of highlights) {
    const arr = byPage.get(h.page) || [];
    arr.push(h);
    byPage.set(h.page, arr);
  }

  const merged: HighlightBox[] = [];
  for (const [, pageHighlights] of byPage) {
    if (pageHighlights.length <= 1) {
      merged.push(...pageHighlights);
      continue;
    }

    // Sort top-to-bottom (highest t first in PDF coords)
    const sorted = [...pageHighlights].sort((a, b) => b.bbox.t - a.bbox.t);

    let current = { ...sorted[0], bbox: { ...sorted[0].bbox } };
    for (let i = 1; i < sorted.length; i++) {
      const next = sorted[i];
      const lineHeight = current.bbox.t - current.bbox.b;
      const gap = current.bbox.b - next.bbox.t;

      // Merge if gap between bottom of current and top of next is small
      // (less than one line height, or they overlap)
      if (gap < lineHeight * 0.8) {
        current.bbox.l = Math.min(current.bbox.l, next.bbox.l);
        current.bbox.r = Math.max(current.bbox.r, next.bbox.r);
        current.bbox.b = Math.min(current.bbox.b, next.bbox.b);
        current.bbox.t = Math.max(current.bbox.t, next.bbox.t);
        // Concatenate text
        if (next.text && !current.text.includes(next.text)) {
          current.text = current.text + ' ' + next.text;
        }
      } else {
        merged.push(current);
        current = { ...next, bbox: { ...next.bbox } };
      }
    }
    merged.push(current);
  }

  return merged;
};

interface PDFViewerProps {
  docId: string;
  chunkId: string;
  pageNum?: number;
  onClose: () => void;
  title?: string;
  searchQuery?: string; // NEW: for sentence-level highlighting
  initialBBox?: { page: number, bbox: { l: number, b: number, r: number, t: number }, text?: string }[]; // IMMEDIATE chunk bboxes with text
  metadata?: Record<string, any>; // All metadata for the document
  dataSource?: string; // Data source for API requests
  semanticHighlightModelConfig?: SummaryModelConfig | null;
  onOpenMetadata?: (metadata: Record<string, any>) => void;
  // Search settings inherited from main search
  searchDenseWeight?: number;
  rerankEnabled?: boolean;
  sectionTypes?: string[];
  keywordBoostShortQueries?: boolean;
  minChunkSize?: number;
  minScore?: number;
  rerankModel?: string | null;
  rerankModelPageSize?: number | null;
  searchModel?: string | null;
  deduplicateEnabled?: boolean;
  fieldBoostEnabled?: boolean;
  fieldBoostFields?: Record<string, number>;
}

const ESTIMATED_PAGE_HEIGHT = 1200; // Approximate height per page for scrollbar
const BUFFER_PAGES = 2; // Number of pages to render before/after current

type SpanMapItem = { span: HTMLElement; start: number; end: number };
type SpanGroup = {
  top: number;
  spans: HTMLElement[];
  minLeft: number;
  maxRight: number;
  maxBottom: number;
};
type PhraseRange = {
  start: number;
  end: number;
  normalizedPhrase: string;
  overlayColor: string;
};

// NFC normalization collapses decomposed Unicode forms (e.g., n + combining
// tilde U+0303) into their precomposed equivalents (\u00F1, U+00F1). Without it,
// PDFs that store diacritics in decomposed form silently fail to match
// search terms typed in precomposed form (and vice versa).
export const normalizePdfText = (text: string): string =>
  text
    .normalize('NFC')
    .toLowerCase()
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .replace(/\s*([.,;:!?])\s*/g, '$1 ')
    .replace(/\s*-\s*/g, '-')
    .trim();

export const normalizePdfTextNoSpaces = (text: string): string =>
  text
    .normalize('NFC')
    .toLowerCase()
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/[.,;:!?'"()\[\]{}\-\s]/g, '')
    .trim();

const mapNoSpaceStartToPdf = (
  pdfText: string,
  noSpaceStart: number,
  phraseNoSpaces: string
) => {
  let pdfCharPos = 0;
  let noSpaceCharPos = 0;
  while (pdfCharPos < pdfText.length && noSpaceCharPos < noSpaceStart) {
    const char = pdfText[pdfCharPos].toLowerCase();
    if (/[a-z0-9]/.test(char)) {
      noSpaceCharPos++;
    }
    pdfCharPos++;
  }

  const phraseLength = phraseNoSpaces.length;
  let endPos = pdfCharPos;
  let counted = 0;
  while (endPos < pdfText.length && counted < phraseLength) {
    const char = pdfText[endPos].toLowerCase();
    if (/[a-z0-9]/.test(char)) {
      counted++;
    }
    endPos++;
  }
  return { start: pdfCharPos, end: endPos };
};

const findPhraseRange = (
  normalizedPdfText: string,
  pdfText: string,
  phrase: string
): PhraseRange | null => {
  const normalizedPhrase = normalizePdfText(phrase);
  const exactStart = normalizedPdfText.indexOf(normalizedPhrase);
  if (exactStart !== -1) {
    return {
      start: exactStart,
      end: exactStart + normalizedPhrase.length,
      normalizedPhrase,
      overlayColor: 'rgba(255, 165, 0, 0.6)'
    };
  }

  const phraseNoSpaces = normalizePdfTextNoSpaces(phrase);
  const pdfNoSpaces = normalizePdfTextNoSpaces(pdfText);
  const noSpaceStart = pdfNoSpaces.indexOf(phraseNoSpaces);
  if (noSpaceStart === -1) {
    return null;
  }

  const mapped = mapNoSpaceStartToPdf(pdfText, noSpaceStart, phraseNoSpaces);
  return {
    start: mapped.start,
    end: mapped.end,
    normalizedPhrase,
    overlayColor: 'var(--highlight-bg)'
  };
};

const buildSpanMap = (spans: HTMLElement[]) => {
  const spanMap: SpanMapItem[] = [];
  let currentPos = 0;
  spans.forEach((span) => {
    const spanText = span.textContent || '';
    spanMap.push({ span, start: currentPos, end: currentPos + spanText.length });
    currentPos += spanText.length;
  });
  return spanMap;
};

const findMatchedSpans = (
  spanMap: SpanMapItem[],
  phraseStart: number,
  phraseEnd: number
) => spanMap.filter((spanItem) => spanItem.start < phraseEnd && spanItem.end > phraseStart).map((item) => item.span);

const sortSpansByPosition = (spans: HTMLElement[]) =>
  spans.sort((a, b) => {
    const rectA = a.getBoundingClientRect();
    const rectB = b.getBoundingClientRect();
    if (Math.abs(rectA.top - rectB.top) > 5) {
      return rectA.top - rectB.top;
    }
    return rectA.left - rectB.left;
  });

const groupSpansByLine = (spans: HTMLElement[], containerRect: DOMRect) => {
  const groups: SpanGroup[] = [];
  spans.forEach((span) => {
    const rect = span.getBoundingClientRect();
    const top = rect.top - containerRect.top;
    let group = groups.find((item) => Math.abs(item.top - top) < 5);
    if (!group) {
      group = {
        top,
        spans: [],
        minLeft: Infinity,
        maxRight: -Infinity,
        maxBottom: top
      };
      groups.push(group);
    }

    const left = rect.left - containerRect.left;
    const right = rect.right - containerRect.left;
    const bottom = rect.bottom - containerRect.top;
    group.spans.push(span);
    group.minLeft = Math.min(group.minLeft, left);
    group.maxRight = Math.max(group.maxRight, right);
    group.maxBottom = Math.max(group.maxBottom, bottom);
  });
  return groups;
};

const appendSpanGroups = (
  groups: SpanGroup[],
  container: HTMLElement,
  bboxKey: string,
  overlayColor: string
) => {
  groups.forEach((group) => {
    const highlightOverlay = document.createElement('div');
    highlightOverlay.className = 'phrase-highlight-overlay';
    highlightOverlay.setAttribute('data-bbox', bboxKey);
    highlightOverlay.style.position = 'absolute';
    highlightOverlay.style.left = `${group.minLeft}px`;
    highlightOverlay.style.top = `${group.top}px`;
    highlightOverlay.style.width = `${group.maxRight - group.minLeft}px`;
    highlightOverlay.style.height = `${group.maxBottom - group.top}px`;
    highlightOverlay.style.backgroundColor = overlayColor;
    highlightOverlay.style.borderRadius = '2px';
    highlightOverlay.style.pointerEvents = 'none';
    // 11 sits above the chunk-box (.highlight-overlay z-index 10) so the
    // orange phrase highlights are not muted by the chunk box's animated
    // blue tint. Below the affordance pills at 12.
    highlightOverlay.style.zIndex = '11';
    container.appendChild(highlightOverlay);
  });
};

type CharMapping = { itemIdx: number; charIdx: number };

const buildPageTextMap = (items: any[]): { fullText: string; charMap: CharMapping[] } => {
  let fullText = '';
  const charMap: CharMapping[] = [];
  for (let i = 0; i < items.length; i++) {
    // NFC-normalize each item's text so charMap positions and the search
    // term operate on the same Unicode form. computeItemEdge (below) uses
    // the same normalized length to keep bbox math consistent.
    const str = (items[i].str || '').normalize('NFC');
    for (let c = 0; c < str.length; c++) {
      charMap.push({ itemIdx: i, charIdx: c });
    }
    fullText += str;
    // Insert a synthetic space between adjacent items that lack whitespace,
    // preventing false cross-item matches (e.g. "of"+"MOH" → "ofMOH" matching "fmoh")
    if (i < items.length - 1 && str.length > 0 && !str.endsWith(' ') && !str.endsWith('\n')) {
      const nextStr = (items[i + 1]?.str || '').normalize('NFC');
      if (nextStr.length > 0 && !nextStr.startsWith(' ')) {
        fullText += ' ';
        charMap.push({ itemIdx: -1, charIdx: -1 });
      }
    }
  }
  return { fullText, charMap };
};

const computeItemEdge = (
  item: any,
  charIdx: number,
  side: 'left' | 'right'
): number => {
  const ix = item.transform[4];
  const iw = item.width || 0;
  // Use NFC-normalized length so it matches the charMap positions stored by
  // buildPageTextMap. Otherwise bbox math drifts on items with decomposed
  // diacritics (different char count between original and normalized).
  const normalizedStr = (item.str || '').normalize('NFC');
  const cw = normalizedStr.length > 0 ? iw / normalizedStr.length : 0;
  if (side === 'left') return ix + charIdx * cw;
  return ix + (charIdx + 1) * cw;
};

const computeMatchBBox = (
  items: any[],
  startMap: CharMapping,
  endMap: CharMapping
): { l: number; b: number; r: number; t: number } | null => {
  let l = Infinity, b = Infinity, r = -Infinity, t = -Infinity;

  for (let idx = startMap.itemIdx; idx <= endMap.itemIdx; idx++) {
    const item = items[idx];
    if (!item.transform) continue;

    const ix = item.transform[4];
    const iy = item.transform[5];
    const iw = item.width || 0;
    const ih = Math.abs(item.transform[3]) || item.height || 10;

    const isStart = idx === startMap.itemIdx;
    const isEnd = idx === endMap.itemIdx;
    const itemL = isStart ? computeItemEdge(item, startMap.charIdx, 'left') : ix;
    const itemR = isEnd ? computeItemEdge(item, endMap.charIdx, 'right') : ix + iw;

    l = Math.min(l, itemL);
    r = Math.max(r, itemR);
    b = Math.min(b, iy);
    t = Math.max(t, iy + ih);
  }

  return l < Infinity ? { l, b, r, t } : null;
};

const parseBBoxItem = (
  bboxItem: any,
  fallbackPage: number
): { page: number; bbox: { l: number; b: number; r: number; t: number } } | null => {
  let page = fallbackPage;
  let coords: number[] | null = null;

  if (Array.isArray(bboxItem) && bboxItem.length === 2 && Array.isArray(bboxItem[1])) {
    page = Number(bboxItem[0]);
    coords = bboxItem[1];
  } else if (Array.isArray(bboxItem) && bboxItem.length === 4 && typeof bboxItem[0] === 'number') {
    coords = bboxItem;
  }

  if (!coords || coords.length < 4) return null;
  return { page, bbox: { l: coords[0], b: coords[1], r: coords[2], t: coords[3] } };
};

// A synthetic space was inserted between PDF items that lack their own
// whitespace. A match that lands on such a position is only illegitimate
// when the search term doesn't ALSO have a space at that offset — that's
// the false-positive case ("of"+"MOH" → matching "fmoh"). When the user's
// term has a space here, the synthetic space lines up with their intent
// and the match is real (e.g. "el niño" spanning split items).
const hasIllegalGapCross = (
  charMap: CharMapping[],
  pos: number,
  endPos: number,
  normalizedSearchTerm: string
): boolean => {
  for (let p = pos; p <= endPos; p++) {
    if (charMap[p].itemIdx < 0 && normalizedSearchTerm[p - pos] !== ' ') {
      return true;
    }
  }
  return false;
};

// Synthetic positions (itemIdx < 0) have no items to read width from, so we
// narrow inward to the first/last real positions for bbox computation.
const narrowToRealItemPositions = (
  charMap: CharMapping[],
  pos: number,
  endPos: number
): { start: number; end: number } | null => {
  let start = pos;
  while (start <= endPos && charMap[start].itemIdx < 0) start++;
  let end = endPos;
  while (end >= start && charMap[end].itemIdx < 0) end--;
  if (end < start) return null;
  return { start, end };
};

export const findTextMatchesOnPage = (
  items: any[],
  searchTerm: string,
  pageNum: number
): HighlightBox[] => {
  if (items.length === 0) return [];

  const { fullText, charMap } = buildPageTextMap(items);
  const lowerText = fullText.toLowerCase();
  // NFC-normalize the search term to match buildPageTextMap's normalization.
  // Otherwise a query with precomposed ñ won't find PDF text that uses the
  // decomposed form (or vice versa).
  const normalizedSearchTerm = searchTerm.normalize('NFC');
  const matches: HighlightBox[] = [];
  let pos = 0;
  let skipped = 0;

  while ((pos = lowerText.indexOf(normalizedSearchTerm, pos)) !== -1) {
    const endPos = pos + normalizedSearchTerm.length - 1;
    if (endPos >= charMap.length) break;

    if (hasIllegalGapCross(charMap, pos, endPos, normalizedSearchTerm)) {
      skipped++;
      pos += 1;
      continue;
    }

    const real = narrowToRealItemPositions(charMap, pos, endPos);
    if (!real) { pos += 1; continue; }

    const bbox = computeMatchBBox(items, charMap[real.start], charMap[real.end]);
    if (bbox) {
      matches.push({
        page: pageNum,
        bbox,
        text: fullText.substring(pos, pos + normalizedSearchTerm.length),
        isTextMatch: true
      });
    }
    pos += 1;
  }

  if (skipped > 0) {
    console.log(`[Text Search] Page ${pageNum}: skipped ${skipped} false cross-item matches for "${normalizedSearchTerm}"`);
  }

  return matches;
};

// === Phrase-highlight cache types & helpers ===
//
// The previous implementation used a `Set<bboxKey>` "checklist" that was
// ticked off the first time any render asked the LLM about a bbox. That gate
// is write-once per render cycle, so a second cascading render (which wipes
// pageContainer.innerHTML) would skip the LLM call and leave the chunk with
// its overlay erased. Result: chunk box visible, phrase highlights missing.
//
// New design: a query-aware Map. Each entry tracks which query produced its
// matches; if a later render asks about the same bbox under a different
// query, we treat it as a miss and re-fire the LLM. After matches arrive we
// can re-draw them on every subsequent render from the cache directly.

type PhraseCacheEntry =
  | { status: 'pending'; query: string }
  | { status: 'done'; query: string; matches: TextMatch[] }
  | { status: 'failed'; query: string };

const bboxKeyFor = (
  pageNumber: number,
  bbox: { l: number; b: number; r: number; t: number }
): string => `${pageNumber}-${bbox.l}-${bbox.t}-${bbox.r}-${bbox.b}`;

type PixelRect = { left: number; right: number; top: number; bottom: number };

const computeBBoxPixelRect = (
  bbox: { l: number; b: number; r: number; t: number },
  scale: number,
  viewportHeight: number
): PixelRect => ({
  left: bbox.l * scale,
  right: bbox.r * scale,
  top: viewportHeight - bbox.t * scale,
  bottom: viewportHeight - bbox.b * scale
});

const findSpansInPixelRect = (
  spans: NodeListOf<Element>,
  pageContainer: HTMLElement,
  rect: PixelRect
): HTMLElement[] => {
  const containerRect = pageContainer.getBoundingClientRect();
  const result: HTMLElement[] = [];
  spans.forEach((span) => {
    const el = span as HTMLElement;
    const sRect = el.getBoundingClientRect();
    const sLeft = sRect.left - containerRect.left;
    const sRight = sRect.right - containerRect.left;
    const sTop = sRect.top - containerRect.top;
    const sBottom = sRect.bottom - containerRect.top;
    const overlaps = !(
      sRight < rect.left || sLeft > rect.right ||
      sBottom < rect.top || sTop > rect.bottom
    );
    if (overlaps) result.push(el);
  });
  return result;
};

// Returns the number of phrase overlays actually appended to the DOM. The
// caller uses this to decide whether to show the no-match affordance: even
// when matches is non-empty, a phrase may fail to align with PDF.js's
// extracted text (whitespace/ligature differences) and end up drawing zero
// overlays. In that case the user should still get visual feedback.
const drawPhraseOverlaysFromMatches = (
  pageContainer: HTMLElement,
  bboxKey: string,
  spansInBox: HTMLElement[],
  matches: TextMatch[]
): number => {
  // Remove any pre-existing overlays for this bbox to avoid duplicates on
  // re-render (zoom, page redraw, etc.). Also remove any no-match pill —
  // we're about to draw real overlays, so the "no specific phrase" message
  // would be a lie. (If we end up drawing zero, the caller restores it.)
  pageContainer
    .querySelectorAll(`.phrase-highlight-overlay[data-bbox="${bboxKey}"]`)
    .forEach((el) => el.remove());
  removeNoMatchAffordance(pageContainer, bboxKey);

  if (spansInBox.length === 0 || matches.length === 0) return 0;

  const pdfTextForMatching = spansInBox.map((s) => s.textContent || '').join('');
  const normalizedPdfText = normalizePdfText(pdfTextForMatching);
  const highlightedRanges: { start: number; end: number }[] = [];
  let drawn = 0;

  matches.forEach((match) => {
    const range = findPhraseRange(normalizedPdfText, pdfTextForMatching, match.matchedText);
    if (!range) return;
    const overlaps = highlightedRanges.some(
      (prev) => range.start < prev.end && range.end > prev.start
    );
    if (overlaps) return;
    highlightedRanges.push({ start: range.start, end: range.end });

    const spanMap = buildSpanMap(spansInBox);
    const matchedSpans = findMatchedSpans(spanMap, range.start, range.end);
    if (matchedSpans.length === 0) return;

    const sortedSpans = sortSpansByPosition(matchedSpans);
    const containerRect = pageContainer.getBoundingClientRect();
    const spanGroups = groupSpansByLine(sortedSpans, containerRect);
    appendSpanGroups(spanGroups, pageContainer, bboxKey, range.overlayColor);
    drawn += spanGroups.length;
  });

  return drawn;
};

const COMPUTING_AFFORDANCE_CLASS = 'phrase-highlight-pending';

const removeComputingAffordance = (
  pageContainer: HTMLElement,
  bboxKey: string
): void => {
  pageContainer
    .querySelectorAll(`.${COMPUTING_AFFORDANCE_CLASS}[data-bbox="${bboxKey}"]`)
    .forEach((el) => el.remove());
};

const drawComputingAffordance = (
  pageContainer: HTMLElement,
  bboxKey: string,
  pixelRect: PixelRect
): void => {
  removeComputingAffordance(pageContainer, bboxKey);
  const indicator = document.createElement('div');
  indicator.className = COMPUTING_AFFORDANCE_CLASS;
  indicator.setAttribute('data-bbox', bboxKey);
  indicator.textContent = 'Computing highlights…';
  Object.assign(indicator.style, {
    position: 'absolute',
    top: `${Math.max(0, pixelRect.top - 22)}px`,
    left: `${pixelRect.left}px`,
    background: 'rgba(0, 102, 204, 0.85)',
    color: 'white',
    fontSize: '10px',
    fontWeight: '500',
    padding: '2px 6px',
    borderRadius: '3px',
    pointerEvents: 'none',
    zIndex: '12',
    whiteSpace: 'nowrap'
  } as Partial<CSSStyleDeclaration>);
  pageContainer.appendChild(indicator);
};

// Affordance shown after the LLM completes but returns zero phrases worth
// highlighting. Conveys "this chunk IS relevant per retrieval, but the LLM
// couldn't pick a specific quotable phrase". Visually similar to
// drawComputingAffordance (same position above the chunk box) but greyed
// out so the user immediately distinguishes "still computing" from "done,
// nothing to show".
const NO_MATCH_AFFORDANCE_CLASS = 'phrase-highlight-no-match';

const removeNoMatchAffordance = (
  pageContainer: HTMLElement,
  bboxKey: string
): void => {
  pageContainer
    .querySelectorAll(`.${NO_MATCH_AFFORDANCE_CLASS}[data-bbox="${bboxKey}"]`)
    .forEach((el) => el.remove());
};

const drawNoMatchAffordance = (
  pageContainer: HTMLElement,
  bboxKey: string,
  pixelRect: PixelRect
): void => {
  // Always remove any prior pending affordance — this transition is
  // "Computing…" → "Topic match — no specific phrase".
  removeComputingAffordance(pageContainer, bboxKey);
  removeNoMatchAffordance(pageContainer, bboxKey);
  const indicator = document.createElement('div');
  indicator.className = NO_MATCH_AFFORDANCE_CLASS;
  indicator.setAttribute('data-bbox', bboxKey);
  indicator.textContent = 'Topic match — no specific phrase';
  Object.assign(indicator.style, {
    position: 'absolute',
    top: `${Math.max(0, pixelRect.top - 22)}px`,
    left: `${pixelRect.left}px`,
    background: 'rgba(110, 110, 110, 0.85)',
    color: 'white',
    fontSize: '10px',
    fontWeight: '500',
    padding: '2px 6px',
    borderRadius: '3px',
    pointerEvents: 'none',
    zIndex: '12',
    whiteSpace: 'nowrap'
  } as Partial<CSSStyleDeclaration>);
  pageContainer.appendChild(indicator);
};

const drawChunkBoxAndIndicator = (
  pageContainer: HTMLElement,
  highlight: HighlightBox,
  scale: number,
  viewportHeight: number
): { pixelRect: PixelRect; chunkBoxElement: HTMLDivElement } => {
  const { bbox } = highlight;
  const x = bbox.l * scale;
  const y = (viewportHeight / scale - bbox.t) * scale;
  const width = (bbox.r - bbox.l) * scale;
  const height = (bbox.t - bbox.b) * scale;
  const padding = 5;

  const div = document.createElement('div');
  div.className = highlight.isTextMatch ? 'text-match-overlay' : 'highlight-overlay';
  Object.assign(div.style, {
    position: 'absolute',
    pointerEvents: 'none',
    zIndex: highlight.isTextMatch ? '15' : '10',
    left: `${x - padding}px`,
    top: `${y - padding}px`,
    width: `${width + padding * 2}px`,
    height: `${height + padding * 2}px`,
    borderRadius: '4px',
    ...(highlight.isTextMatch
      ? { background: 'rgba(255, 165, 0, 0.4)', border: '2px solid rgba(255, 140, 0, 0.8)' }
      : { background: 'var(--pdf-highlight-bg)', border: 'var(--pdf-highlight-border)' })
  });
  div.title = (highlight.text || '').substring(0, 100);
  pageContainer.appendChild(div);

  const indicator = document.createElement('div');
  indicator.className = 'highlight-indicator';
  Object.assign(indicator.style, {
    position: 'absolute',
    pointerEvents: 'none',
    backgroundColor: highlight.isTextMatch ? 'rgba(255, 140, 0, 0.9)' : 'rgba(0, 102, 204, 0.8)',
    zIndex: '10',
    right: '0',
    top: `${y}px`,
    width: '12px',
    height: `${height}px`,
    borderRadius: '6px 0 0 6px'
  });
  pageContainer.appendChild(indicator);

  return {
    pixelRect: { left: x, right: x + width, top: y, bottom: y + height },
    chunkBoxElement: div
  };
};

export const PDFViewer: React.FC<PDFViewerProps> = ({
  docId,
  chunkId,
  pageNum = 1,
  onClose,
  title = 'Document',
  searchQuery = '',
  initialBBox = [],
  metadata = {},
  dataSource = '',
  semanticHighlightModelConfig,
  onOpenMetadata,
  searchDenseWeight = 0.8,
  rerankEnabled = true,
  sectionTypes = [],
  keywordBoostShortQueries = true,
  minChunkSize = 100,
  minScore = 0,
  rerankModel = null,
  rerankModelPageSize = null,
  searchModel = null,
  deduplicateEnabled = true,
  fieldBoostEnabled = true,
  fieldBoostFields = {},
}) => {
  // Extract fields from metadata (check multiple possible field locations)
  const webUrl = metadata.report_url || metadata.map_report_url || metadata.src_doc_raw_metadata?.report_url;
  const pdfUrl = metadata.pdf_url || metadata.map_pdf_url || metadata.src_doc_raw_metadata?.pdf_url;
  const organization = metadata.organization;
  const year = metadata.year;
  const score = metadata.score;
  const [pdfDoc, setPdfDoc] = useState<any>(null);
  const [currentPage, setCurrentPage] = useState(pageNum);
  const [totalPages, setTotalPages] = useState(0);
  const [scale, setScale] = useState(1.5);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [highlights, setHighlights] = useState<HighlightBox[]>([]);
  const [renderedPages, setRenderedPages] = useState<Map<number, boolean>>(new Map());
  const [actualPageHeight, setActualPageHeight] = useState(ESTIMATED_PAGE_HEIGHT);
  const actualPageHeightRef = useRef(ESTIMATED_PAGE_HEIGHT); // Ref for immediate access during render
  const [metadataExpanded, setMetadataExpanded] = useState(false);

  // TOC modal state
  const [tocModalOpen, setTocModalOpen] = useState(false);
  const [documentToc, setDocumentToc] = useState<string>('');
  const [loadingToc, setLoadingToc] = useState(false);

  // In-PDF search state
  const [inPdfSearchQuery, setInPdfSearchQuery] = useState('');
  const [inPdfSearchResults, setInPdfSearchResults] = useState<HighlightBox[]>([]);
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);
  const [isSearching, setIsSearching] = useState(false);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const pagesContainerRef = useRef<HTMLDivElement>(null);
  const renderTasksRef = useRef<Map<number, any>>(new Map());
  const isScrollingProgrammatically = useRef(false);
  const lastProgrammaticScrollTime = useRef(0);
  const hasSnappedToHighlight = useRef(false);
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Phrase-highlight cache: query-aware, per-bbox. Survives re-renders so we
  // can redraw cached overlays after pageContainer.innerHTML wipes (zoom,
  // force re-render). See PhraseCacheEntry above for the state machine.
  const phraseCacheRef = useRef<Map<string, PhraseCacheEntry>>(new Map());
  // In-flight LLM requests, keyed by bboxKey. We abort prior requests when
  // the user changes the in-doc query so stale responses don't paint over a
  // newer query's overlays.
  const inFlightControllersRef = useRef<Map<string, AbortController>>(new Map());
  // IntersectionObservers, keyed by bboxKey. Each observer fires once when
  // the chunk box becomes visible, then disconnects.
  const phraseObserversRef = useRef<Map<string, IntersectionObserver>>(new Map());

  // Calculate scale based on viewport width for mobile
  useEffect(() => {
    const updateScale = () => setScale(getResponsiveScale());
    updateScale();
    window.addEventListener('resize', updateScale);
    return () => window.removeEventListener('resize', updateScale);
  }, []);

  // Tear down all phrase-highlight state. Aborts in-flight LLM requests so
  // their late responses don't paint over a fresher query, disconnects all
  // pending IntersectionObservers, and clears the cache.
  const clearAllPhraseState = () => {
    inFlightControllersRef.current.forEach((c) => c.abort());
    inFlightControllersRef.current.clear();
    phraseObserversRef.current.forEach((o) => o.disconnect());
    phraseObserversRef.current.clear();
    phraseCacheRef.current.clear();
  };

  // Reset snap state when document/chunk changes
  useEffect(() => {
    hasSnappedToHighlight.current = false;
    clearAllPhraseState();
    // Always enable programmatic scrolling when doc/chunk/page changes
    isScrollingProgrammatically.current = true;
    // Navigate to the requested page (useState only captures the initial
    // value, so prop changes need to be synchronised explicitly)
    setCurrentPage(pageNum);
    // Clear in-PDF search results when opening a new document
    setInPdfSearchResults([]);
    setInPdfSearchQuery('');
    setCurrentMatchIndex(0);
  }, [docId, chunkId, pageNum]);

  // Component unmount cleanup: abort any in-flight requests and disconnect
  // observers so we don't leak resources or paint into a torn-down DOM.
  useEffect(() => {
    return () => {
      clearAllPhraseState();
    };
  }, []);

  // Load PDF
  useEffect(() => {
    const initPDF = async () => {
      if (window.pdfjsLib) {
        await loadPDF();
        return;
      }

      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
      script.async = true;
      script.onload = async () => {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc =
          'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        await loadPDF();
      };
      script.onerror = () => {
        setError('Failed to load PDF.js library');
        setLoading(false);
      };
      document.body.appendChild(script);
    };

    initPDF();
  }, [docId]);

  // Load highlights
  useEffect(() => {
    // Don't overwrite search highlights with initial highlights
    if (inPdfSearchQuery || inPdfSearchResults.length > 0) {
      return;
    }

    // Set initial bbox highlights immediately (no API call needed)
    if (initialBBox && initialBBox.length > 0) {
      const immediateHighlights: HighlightBox[] = initialBBox.map(item => ({
        page: item.page,
        bbox: item.bbox,
        text: item.text || '' // Pass chunk text for semantic matching
      }));
      const merged = mergeSequentialHighlights(immediateHighlights);
      console.log(`[Highlights] Setting ${merged.length} IMMEDIATE bbox highlights (merged from ${immediateHighlights.length}) with text`);
      setHighlights(merged);
    }

    // Then load additional highlights asynchronously if needed (and we don't already have bbox highlights)
    if (chunkId && pdfDoc && initialBBox.length === 0) {
      loadHighlights();
    }
  }, [chunkId, pdfDoc, initialBBox, inPdfSearchQuery, inPdfSearchResults]);

  // Render visible pages when current page or search results change
  // Merged into a single effect to prevent two concurrent renderVisiblePages calls
  // racing and cancelling each other's PDF.js render tasks
  const prevSearchResultsRef = useRef<HighlightBox[]>([]);
  useEffect(() => {
    if (pdfDoc && currentPage > 0) {
      const searchResultsChanged = inPdfSearchResults !== prevSearchResultsRef.current;
      prevSearchResultsRef.current = inPdfSearchResults;
      renderVisiblePages(searchResultsChanged && inPdfSearchResults.length > 0);
    }
  }, [pdfDoc, currentPage, totalPages, inPdfSearchResults]);

  // Re-render all pages when scale changes
  useEffect(() => {
    if (pdfDoc && currentPage > 0) {
      // Clear all rendered pages and force re-render
      setRenderedPages(new Map());
      // Reset snap state so scroll will happen after re-render
      hasSnappedToHighlight.current = false;
      renderVisiblePages(true);
    }
  }, [scale]);

  // Re-position all rendered pages when actual page height changes
  useEffect(() => {
    if (actualPageHeight !== ESTIMATED_PAGE_HEIGHT && pagesContainerRef.current) {
      // Update positions of all existing page containers
      for (let i = 1; i <= totalPages; i++) {
        const pageContainer = document.getElementById(`pdf-page-${i}`);
        if (pageContainer) {
          pageContainer.style.top = `${(i - 1) * actualPageHeight}px`;
        }
      }
    }
  }, [actualPageHeight, totalPages]);

  // Update scroll position when page changes programmatically
  // Handle scrolling to page or highlight
  // This effect handles IMMEDIATE scroll to page, then adjusts for highlights when they load
  useEffect(() => {
    if (!scrollContainerRef.current || totalPages === 0) {
      return;
    }

    // Wait for pages to render before attempting scroll
    // Only skip if still at the default estimate (page height not yet measured)
    if (actualPageHeight === ESTIMATED_PAGE_HEIGHT) {
      return;
    }

    const pageHighlights = highlights.filter(h => h.page === currentPage);

    let shouldScroll = false;

    // Find the target highlight for scroll offset calculation
    const targetHighlight = getTargetHighlight(pageHighlights);

    // IMMEDIATE scroll when programmatic flag is set (opening new doc/chunk/page)
    // Don't wait for highlights - scroll to page immediately
    if (isScrollingProgrammatically.current) {
      shouldScroll = true;
      // If highlights are already available, use them; otherwise just scroll to page top
      if (pageHighlights.length > 0) {
        hasSnappedToHighlight.current = true;
        console.log(`[Scroll] IMMEDIATE scroll to page ${currentPage} WITH highlights (will recalculate in callback)`);
      } else {
        console.log(`[Scroll] IMMEDIATE scroll to page ${currentPage} (will recalculate in callback, highlights will adjust later)`);
        // Don't mark as snapped yet - let the secondary scroll happen when highlights load
        // hasSnappedToHighlight.current stays false
      }
      // NOTE: Don't consume isScrollingProgrammatically here. It's consumed in the
      // setTimeout callback below. This ensures that if actualPageHeight changes
      // (e.g. landscape→portrait page renders), the effect re-runs and recalculates.
    }
    // SECONDARY scroll when highlights load after initial page scroll
    else if (!hasSnappedToHighlight.current && pageHighlights.length > 0) {
      // Highlights just loaded - adjust scroll position to show them
      shouldScroll = true;
      hasSnappedToHighlight.current = true;
      console.log(`[Scroll] ADJUSTING scroll for ${pageHighlights.length} highlights (will recalculate in callback)`);
    }

    if (shouldScroll) {
      // Cancel any pending scroll timer so we recalculate with the latest height.
      // This handles the case where actualPageHeight changes multiple times
      // (e.g. landscape page renders first, then portrait page updates the height).
      if (scrollTimerRef.current) {
        clearTimeout(scrollTimerRef.current);
      }
      // Recalculate scroll target inside the callback using the ref (always up-to-date)
      // to avoid stale-closure issues when page height changes between effect and callback
      const hasHighlightOffset = targetHighlight != null;
      const bboxT = targetHighlight?.bbox.t ?? 0;
      scrollTimerRef.current = setTimeout(() => {
        requestAnimationFrame(() => {
          if (scrollContainerRef.current) {
            const latestHeight = actualPageHeightRef.current;
            let finalTarget = (currentPage - 1) * latestHeight;
            if (hasHighlightOffset) {
              const vpHeightPdfUnits = (latestHeight - 20) / scale;
              let hOffset = (vpHeightPdfUnits - bboxT) * scale;
              const padding = window.innerWidth <= 640 ? 50 : 100;
              hOffset = Math.max(0, hOffset - padding);
              finalTarget += hOffset;
            }
            console.log(`[Scroll] Setting scrollTop=${finalTarget} (pageHeight=${latestHeight}, page=${currentPage})`);
            lastProgrammaticScrollTime.current = Date.now();
            scrollContainerRef.current.scrollTop = finalTarget;
          }
          // Consume the programmatic flag AFTER the scroll is set
          isScrollingProgrammatically.current = false;
          scrollTimerRef.current = null;
        });
      }, 150);
    }
  }, [currentPage, totalPages, actualPageHeight, highlights, scale, currentMatchIndex, inPdfSearchResults]);

  // Handle scroll to determine current page
  const handleScroll = () => {
    if (!scrollContainerRef.current || totalPages === 0) return;

    // If user scrolls manually (not within 100ms of programmatic scroll), disable auto-snap to highlight
    const timeSinceLastProgrammaticScroll = Date.now() - lastProgrammaticScrollTime.current;
    if (!isScrollingProgrammatically.current && timeSinceLastProgrammaticScroll > 100) {
      hasSnappedToHighlight.current = true;
    }

    if (isScrollingProgrammatically.current) return;

    // Don't update page number if we just did a programmatic scroll (within 200ms)
    // This prevents the page from changing before highlights load
    if (timeSinceLastProgrammaticScroll < 200) {
      return;
    }

    const scrollTop = scrollContainerRef.current.scrollTop;
    const newPage = Math.floor(scrollTop / actualPageHeight) + 1;
    const clampedPage = Math.max(1, Math.min(totalPages, newPage));

    if (clampedPage !== currentPage) {
      setCurrentPage(clampedPage);
    }
  };

  const loadPDF = async () => {
    try {
      const url = `${API_BASE_URL}/pdf/${docId}?data_source=${dataSource}`;
      const loadingTask = window.pdfjsLib.getDocument(url);
      const pdf = await loadingTask.promise;

      setPdfDoc(pdf);
      setTotalPages(pdf.numPages);
      isScrollingProgrammatically.current = true;  // Enable scroll for initial page
      setCurrentPage(pageNum);
      setLoading(false);
    } catch (err: any) {
      setError(`Failed to load PDF: ${err.message}`);
      setLoading(false);
    }
  };

  const loadHighlights = async () => {
    try {
      console.log(`[Highlights] Fetching additional highlights from API for chunk ${chunkId}...`);
      const response = await axios.get<{ highlights: HighlightBox[]; total: number }>(
        `${API_BASE_URL}/highlight/chunk/${chunkId}`
      );
      const data = response.data as { highlights?: HighlightBox[]; total?: number };
      const apiHighlights = data.highlights || [];
      console.log(`[Highlights] Received ${apiHighlights.length} highlights from API`);

      // Merge with existing immediate highlights (avoid duplicates), then merge sequential
      setHighlights(prevHighlights => {
        const existingPages = new Set(prevHighlights.map(h => `${h.page}-${h.bbox.l}-${h.bbox.t}`));
        const newHighlights = apiHighlights.filter(h =>
          !existingPages.has(`${h.page}-${h.bbox.l}-${h.bbox.t}`)
        );
        console.log(`[Highlights] Adding ${newHighlights.length} new highlights (${prevHighlights.length} already present)`);
        return mergeSequentialHighlights([...prevHighlights, ...newHighlights]);
      });
    } catch (err) {
      console.error('Error loading highlights:', err);
    }
  };

  const renderVisiblePages = async (force = false) => {
    if (!pdfDoc || !pagesContainerRef.current) return;

    // Calculate range of pages to render (current + buffer)
    const startPage = Math.max(1, currentPage - BUFFER_PAGES);
    const endPage = Math.min(totalPages, currentPage + BUFFER_PAGES);

    // Render pages in range
    for (let pageNum = startPage; pageNum <= endPage; pageNum++) {
      if (force || !renderedPages.has(pageNum)) {
        await renderPage(pageNum);
      }
    }

    // Clean up pages that are too far from current view
    const pagesToRemove: number[] = [];
    renderedPages.forEach((_, pageNum) => {
      if (pageNum < startPage - BUFFER_PAGES || pageNum > endPage + BUFFER_PAGES) {
        pagesToRemove.push(pageNum);
      }
    });

    if (pagesToRemove.length > 0) {
      const newRenderedPages = new Map(renderedPages);
      pagesToRemove.forEach(pageNum => {
        const pageEl = document.getElementById(`pdf-page-${pageNum}`);
        if (pageEl) {
          pageEl.innerHTML = '';
        }
        newRenderedPages.delete(pageNum);
      });
      setRenderedPages(newRenderedPages);
    }
  };

  const updatePageHeights = (calculatedHeight: number, pageNumber: number) => {
    if (actualPageHeightRef.current === ESTIMATED_PAGE_HEIGHT || Math.abs(calculatedHeight - actualPageHeightRef.current) > 10) {
      console.log(`Setting actualPageHeight from page ${pageNumber}: ${calculatedHeight}px`);
      actualPageHeightRef.current = calculatedHeight;
      setActualPageHeight(calculatedHeight);
      document.querySelectorAll('[id^="pdf-page-"]').forEach(el => {
        const match = el.id.match(/pdf-page-(\d+)/);
        if (match) {
          const pNum = parseInt(match[1], 10);
          (el as HTMLElement).style.top = `${(pNum - 1) * calculatedHeight}px`;
        }
      });
    }
  };

  const getOrCreatePageContainer = (pageNumber: number): HTMLDivElement => {
    const heightToUse = actualPageHeightRef.current;
    let container = document.getElementById(`pdf-page-${pageNumber}`) as HTMLDivElement;
    if (!container) {
      container = document.createElement('div');
      container.id = `pdf-page-${pageNumber}`;
      container.className = 'pdf-page-wrapper';
      container.style.position = 'absolute';
      container.style.top = `${(pageNumber - 1) * heightToUse}px`;
      container.style.left = '50%';
      container.style.transform = 'translateX(-50%)';
      container.style.overflow = 'visible';
      container.style.marginBottom = '20px';
      pagesContainerRef.current!.appendChild(container);
    } else {
      container.style.top = `${(pageNumber - 1) * heightToUse}px`;
    }
    return container;
  };

  // Async LLM round-trip + DOM update for a single bbox. Caches its result on
  // success / failure, draws a "Computing highlights…" affordance while the
  // request is in flight, and aborts cleanly if the user fires a new query.
  const runSemanticHighlightForBBox = async (
    bboxKey: string,
    pageNumber: number,
    bbox: HighlightBox['bbox'],
    chunkText: string,
    effectiveQuery: string,
    pixelRect: PixelRect
  ): Promise<void> => {
    const initialContainer = document.getElementById(`pdf-page-${pageNumber}`) as HTMLDivElement | null;
    if (!initialContainer) return;

    // Cancel any prior in-flight request for this bbox before starting a new one
    const prior = inFlightControllersRef.current.get(bboxKey);
    if (prior) prior.abort();

    const controller = new AbortController();
    inFlightControllersRef.current.set(bboxKey, controller);
    phraseCacheRef.current.set(bboxKey, { status: 'pending', query: effectiveQuery });
    drawComputingAffordance(initialContainer, bboxKey, pixelRect);

    try {
      console.log(`[Text Layer] [BBox ${bboxKey}] Starting semantic match for query: "${effectiveQuery}"`);
      const matches = await findSemanticMatches(
        chunkText,
        effectiveQuery,
        0.4,
        semanticHighlightModelConfig,
        controller.signal
      );

      // The page DOM may have changed during the await. Re-fetch by id.
      const currentContainer = document.getElementById(`pdf-page-${pageNumber}`) as HTMLDivElement | null;
      if (!currentContainer) {
        phraseCacheRef.current.delete(bboxKey);
        return;
      }
      removeComputingAffordance(currentContainer, bboxKey);

      // Cache the LLM result FIRST, before any paint attempt. If the page
      // DOM is in transition (e.g., fast navigation triggered a
      // renderVisiblePages cleanup mid-flight), the cache stays correct and
      // schedulePhraseHighlightForBBox's cache-hit path will paint on the
      // next renderPage cycle. Caching as 'failed' here would silently
      // swallow a perfectly valid empty-matches result.
      phraseCacheRef.current.set(bboxKey, { status: 'done', query: effectiveQuery, matches });
      console.log(`[Text Layer] [BBox ${bboxKey}] ✅ done with ${matches.length} matches`);

      // The no-match affordance only depends on pageContainer and pixelRect
      // — NOT on the text layer or spans. Paint it immediately when the LLM
      // returns nothing, regardless of whether the textLayer is currently
      // present. Otherwise the user sees "Computing highlights…" disappear
      // with no replacement when the LLM resolves while the DOM is mid-
      // rebuild.
      if (matches.length === 0) {
        // The chunk made it through retrieval (it IS topically relevant) but
        // the LLM extractor found no specific phrase to highlight.
        drawNoMatchAffordance(currentContainer, bboxKey, pixelRect);
        return;
      }

      // We have matches; try to paint the phrase overlays.
      const textLayerEl = currentContainer.querySelector('.textLayer');
      if (!textLayerEl) {
        // textLayer is transient — wait for the next render's cache-hit path
        // to retry rather than show a misleading no-match pill now.
        return;
      }
      const spans = textLayerEl.querySelectorAll('span');
      const spansInBox = findSpansInPixelRect(spans, currentContainer, pixelRect);
      const drawnCount =
        spansInBox.length > 0
          ? drawPhraseOverlaysFromMatches(currentContainer, bboxKey, spansInBox, matches)
          : 0;

      if (drawnCount === 0) {
        // The LLM found phrases but we couldn't paint any visible overlay.
        // Causes: spansInBox empty, or every phrase failed to align with the
        // PDF.js text extraction (whitespace/hyphenation/ligature drift).
        // Either way the user sees no inline highlight, so they need an
        // explanation — fall back to the no-match affordance.
        console.log(
          `[Text Layer] [BBox ${bboxKey}] LLM returned ${matches.length} phrases but 0 overlays drew → no-match`
        );
        drawNoMatchAffordance(currentContainer, bboxKey, pixelRect);
      }
    } catch (err) {
      const ctn = document.getElementById(`pdf-page-${pageNumber}`) as HTMLElement | null;
      if (ctn) removeComputingAffordance(ctn, bboxKey);

      if ((err as { name?: string })?.name === 'AbortError') {
        // Aborted (e.g. query changed). Drop the entry so the next query
        // sees a clean miss and re-runs the LLM.
        phraseCacheRef.current.delete(bboxKey);
        console.log(`[Text Layer] [BBox ${bboxKey}] aborted`);
      } else {
        // LLM threw (network, server 500, etc.). Two things matter for UX:
        //   1. Show the user *something* — silently leaving the chunk box
        //      blank looks like the system stalled. We draw the no-match
        //      affordance for immediate feedback.
        //   2. Delete the cache entry instead of marking 'failed'. On the
        //      next renderPage cycle, schedulePhraseHighlightForBBox sees a
        //      cache miss and re-attaches an observer — so the LLM is
        //      auto-retried when the user navigates away and back.
        console.error(`[Text Layer] [BBox ${bboxKey}] semantic match failed:`, err);
        if (ctn) drawNoMatchAffordance(ctn, bboxKey, pixelRect);
        phraseCacheRef.current.delete(bboxKey);
      }
    } finally {
      // Only delete if we're still the current controller for this bbox.
      if (inFlightControllersRef.current.get(bboxKey) === controller) {
        inFlightControllersRef.current.delete(bboxKey);
      }
    }
  };

  // Decide what to do for a chunk highlight on render: redraw cached overlays,
  // show pending affordance, skip (failed/in-flight under same query), or
  // attach an IntersectionObserver that fires the LLM when the chunk box
  // scrolls into view. This is the heart of the visibility-gated rewrite.
  const schedulePhraseHighlightForBBox = (
    pageContainer: HTMLDivElement,
    pageNumber: number,
    highlight: HighlightBox,
    chunkBoxElement: HTMLDivElement,
    pixelRect: PixelRect,
    textSpans: NodeListOf<Element>,
    effectiveQuery: string
  ): void => {
    const { bbox, text: chunkText } = highlight;
    if (!chunkText) return;

    const bboxKey = bboxKeyFor(pageNumber, bbox);
    const cached = phraseCacheRef.current.get(bboxKey);

    // Cache hit for the current query — skip the network entirely.
    if (cached && cached.query === effectiveQuery) {
      if (cached.status === 'done') {
        if (cached.matches.length === 0) {
          drawNoMatchAffordance(pageContainer, bboxKey, pixelRect);
          console.log(`[Text Layer] [BBox ${bboxKey}] cache hit: done with 0 matches → no-match affordance`);
          return;
        }
        const spansInBox = findSpansInPixelRect(textSpans, pageContainer, pixelRect);
        const drawnCount =
          spansInBox.length > 0
            ? drawPhraseOverlaysFromMatches(pageContainer, bboxKey, spansInBox, cached.matches)
            : 0;
        if (drawnCount === 0) {
          // LLM had phrases but they didn't paint as overlays (alignment /
          // span-overlap failure). Show the no-match pill so the user always
          // gets feedback when there's no visible inline highlight.
          drawNoMatchAffordance(pageContainer, bboxKey, pixelRect);
          console.log(`[Text Layer] [BBox ${bboxKey}] cache hit: done with ${cached.matches.length} matches but 0 overlays drew → no-match`);
        } else {
          console.log(`[Text Layer] [BBox ${bboxKey}] cache hit: ${drawnCount} overlay group(s) drawn`);
        }
        return;
      }
      if (cached.status === 'pending') {
        // An in-flight LLM call from a prior render of this page will resolve
        // and paint into the (possibly fresh) DOM container. Show the
        // affordance again because innerHTML was wiped.
        drawComputingAffordance(pageContainer, bboxKey, pixelRect);
        console.log(`[Text Layer] [BBox ${bboxKey}] cache hit: pending → Computing affordance`);
        return;
      }
      // status === 'failed' — fall through to the cache-miss path so a fresh
      // observer is attached and the LLM is re-tried. This handles two cases:
      //   - Stale 'failed' entries from a previous code version that may
      //     persist in memory (HMR keeps refs alive).
      //   - Genuine retry: if the LLM was transiently broken last time,
      //     give it another shot on the next visit.
      console.log(`[Text Layer] [BBox ${bboxKey}] cache hit: failed → falling through to retry`);
    }

    // Cache miss or stale-query (or stale 'failed') — fire on visibility, not eagerly.
    // Disconnect any prior observer for this bbox key (e.g. previous render).
    const priorObserver = phraseObserversRef.current.get(bboxKey);
    if (priorObserver) priorObserver.disconnect();

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          observer.disconnect();
          phraseObserversRef.current.delete(bboxKey);
          console.log(`[Text Layer] [BBox ${bboxKey}] observer fired → starting LLM call`);
          void runSemanticHighlightForBBox(
            bboxKey,
            pageNumber,
            bbox,
            chunkText,
            effectiveQuery,
            pixelRect
          );
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(chunkBoxElement);
    phraseObserversRef.current.set(bboxKey, observer);
    console.log(`[Text Layer] [BBox ${bboxKey}] observer attached, awaiting visibility`);
  };

  const renderPage = async (pageNumber: number) => {
    if (!pdfDoc || !pagesContainerRef.current) return;

    try {
      // Cancel any ongoing render for this page
      const existingTask = renderTasksRef.current.get(pageNumber);
      if (existingTask) {
        existingTask.cancel();
      }

      const page = await pdfDoc.getPage(pageNumber);
      const viewport = page.getViewport({ scale });

      // Update actual page height based on ANY rendered page (if not yet set properly)
      updatePageHeights(viewport.height + 20, pageNumber);

      // Get or create page container
      const pageContainer = getOrCreatePageContainer(pageNumber);

      // Clear existing content
      pageContainer.innerHTML = '';

      // Canvas
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      if (!context) return;

      const outputScale = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      canvas.style.display = 'block';

      pageContainer.appendChild(canvas);

      // Render PDF
      const renderContext = {
        canvasContext: context,
        viewport: viewport,
        transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null
      };

      const renderTask = page.render(renderContext);
      renderTasksRef.current.set(pageNumber, renderTask);
      await renderTask.promise;
      renderTasksRef.current.delete(pageNumber);

      // Text layer
      const textLayer = document.createElement('div');
      textLayer.className = 'textLayer';
      Object.assign(textLayer.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        width: `${viewport.width}px`,
        height: `${viewport.height}px`,
        overflow: 'visible',
        opacity: '1',
        lineHeight: '1.0',
        pointerEvents: 'auto',
        zIndex: '2' // Above canvas (canvas is z-index 1 or default)
      });
      textLayer.style.setProperty('--scale-factor', scale.toString());
      pageContainer.appendChild(textLayer);

      const textContent = await page.getTextContent();
      await window.pdfjsLib.renderTextLayer({
        textContent,
        container: textLayer,
        viewport,
        textDivs: []
      });

      // Make text layer transparent FIRST (like test script) - this ensures text is always readable
      textLayer.style.color = 'transparent';

      // Get highlights for this page
      // Determine effective search query (either from props or in-PDF search)
      // Prioritize in-PDF search query if it exists, so user sees highlights for what they are currently typing/searching
      const effectiveSearchQuery = inPdfSearchQuery || searchQuery;
      const pageHighlights = highlights.filter(h => h.page === pageNumber);

      // Phase 1: Draw chunk boxes synchronously. These appear immediately and
      // never depend on the LLM. Capture each box's element so we can attach
      // an IntersectionObserver to it for visibility-gated phrase highlighting.
      console.log(`[Chunk Highlights] Rendering ${pageHighlights.length} chunk highlights for page ${pageNumber}`);
      const drawnChunkBoxes = pageHighlights.map((highlight) => ({
        highlight,
        ...drawChunkBoxAndIndicator(pageContainer, highlight, scale, viewport.height)
      }));

      console.log(`[Text Layer]Page ${pageNumber}: searchQuery = '${effectiveSearchQuery}', inPdfSearchQuery = '${inPdfSearchQuery}', highlights = ${pageHighlights.length}`);

      // Phase 2: Visibility-gated phrase highlighting. The LLM call is only
      // fired when a chunk box scrolls into the viewport. Cached matches are
      // re-drawn immediately (no network round-trip on zoom / re-render).
      const semanticEnabled =
        PDF_SEMANTIC_HIGHLIGHTS &&
        Boolean(effectiveSearchQuery && effectiveSearchQuery.trim()) &&
        pageHighlights.length > 0;

      if (semanticEnabled) {
        const textSpans = textLayer.querySelectorAll('span');
        if (textSpans.length === 0) {
          console.warn('[Text Layer] No text spans found! Text layer may not be ready.');
        } else {
          drawnChunkBoxes.forEach(({ highlight, chunkBoxElement, pixelRect }) => {
            schedulePhraseHighlightForBBox(
              pageContainer,
              pageNumber,
              highlight,
              chunkBoxElement,
              pixelRect,
              textSpans,
              effectiveSearchQuery
            );
          });
        }
      }

      // Page label
      const label = document.createElement('div');
      label.textContent = `Page ${pageNumber} `;
      Object.assign(label.style, {
        position: 'absolute',
        top: '10px',
        right: '10px',
        background: 'rgba(0,0,0,0.7)',
        color: 'white',
        padding: '4px 8px',
        borderRadius: '4px',
        fontSize: '12px',
        fontWeight: 'bold',
        pointerEvents: 'none',
        zIndex: '100'
      });
      pageContainer.appendChild(label);

      // Mark as rendered
      setRenderedPages(prev => new Map(prev).set(pageNumber, true));
    } catch (err: any) {
      if (err.name === 'RenderingCancelledException') {
        console.log('Rendering cancelled for page', pageNumber);
      } else {
        console.error(`Error rendering page ${pageNumber}: `, err);
      }
    }
  };

  const goToPage = (page: number) => {
    if (page >= 1 && page <= totalPages) {
      isScrollingProgrammatically.current = true;
      setCurrentPage(page);
    }
  };

  // Zoom functions
  const handleZoomIn = () => {
    setScale(prev => Math.min(prev + 0.25, 3.0)); // Max 3x zoom
  };

  const handleZoomOut = () => {
    setScale(prev => Math.max(prev - 0.25, 0.5)); // Min 0.5x zoom
  };

  const handleResetZoom = () => setScale(getResponsiveScale());

  // Get the target highlight to scroll to
  const getTargetHighlight = (pageHighlights: HighlightBox[]): HighlightBox | null => {
    if (pageHighlights.length === 0) return null;

    // If we're in search mode, scroll to the specific current match
    if (inPdfSearchResults.length > 0 && currentMatchIndex < inPdfSearchResults.length) {
      return inPdfSearchResults[currentMatchIndex];
    }

    // Otherwise, find the topmost highlight on the page
    // In PDF coordinates, bbox.t is measured from bottom, so larger bbox.t = higher on page
    return pageHighlights.reduce((prev, current) =>
      (prev.bbox.t > current.bbox.t) ? prev : current
    );
  };

  // In-PDF search: semantic search via API filtered to this document,
  // plus local text matches for literal keyword hits
  const performInPdfSearch = async (query: string) => {
    if (!query.trim()) {
      setInPdfSearchResults([]);
      setCurrentMatchIndex(0);
      setHighlights([]);
      clearAllPhraseState();
      return;
    }

    setIsSearching(true);
    try {
      // --- Semantic search via API ---
      // Recency parameters (recency_boost, recency_weight, recency_scale_days)
      // are intentionally NOT sent: in-doc search is filtered to a single
      // document via `title`, so any recency boost has nothing to compare
      // against and would be dead weight on the request.
      //
      // auto_min_score is always enabled for in-doc search. Without it the
      // API returns up to `limit` (100) chunks regardless of relevance, which
      // pads the "X of N" counter with the long tail of barely-related
      // chunks. The server-side 30th-percentile filter drops them before
      // they reach the client. (Regular search has this as an opt-in toggle
      // because cross-doc result sets can be more varied; in-doc, where
      // we're scoped to a single document, always-on is the safer default.)
      // Build params. We intentionally inherit ranker / dedupe / boost
      // settings from the parent (so group-level overrides apply), and we
      // enforce both a percentile filter (auto_min_score) and an absolute
      // relevance cutoff (min_score = PDF_SEARCH_SEMANTIC_CUTOFF). Chunks
      // whose stored text contains the query verbatim bypass the cutoff
      // (include_exact_matches=true) so literal hits are always reachable.
      // Recency_* params are intentionally omitted — meaningless when the
      // result set is filtered to a single document via `title`.
      const params: any = {
        q: query,
        limit: 100,
        title: title,
        data_source: dataSource,
        dense_weight: searchDenseWeight.toString(),
        rerank: rerankEnabled.toString(),
        keyword_boost_short_queries: keywordBoostShortQueries.toString(),
        auto_min_score: 'true',
        deduplicate: deduplicateEnabled.toString(),
        field_boost: fieldBoostEnabled.toString(),
        min_score: PDF_SEARCH_SEMANTIC_CUTOFF.toString(),
        include_exact_matches: 'true',
      };
      if (sectionTypes && sectionTypes.length > 0) {
        params.section_types = sectionTypes.join(',');
      }
      if (minChunkSize > 0) {
        params.min_chunk_size = minChunkSize.toString();
      }
      if (rerankModel) {
        params.rerank_model = rerankModel;
      }
      if (rerankModelPageSize != null && rerankModelPageSize > 0) {
        params.rerank_model_page_size = rerankModelPageSize.toString();
      }
      if (searchModel) {
        params.model = searchModel;
      }
      if (fieldBoostEnabled && Object.keys(fieldBoostFields).length > 0) {
        params.field_boost_fields = Object.entries(fieldBoostFields)
          .map(([f, w]) => `${f}:${w}`)
          .join(',');
      }

      const response = await axios.get(`${API_BASE_URL}/search`, { params });
      const data = response.data as { results?: any[] };
      let docResults = data.results || [];
      if (minScore > 0) {
        // User's regular-search minScore slider is layered on top of the
        // backend cutoff (defense in depth). Backend already enforces
        // PDF_SEARCH_SEMANTIC_CUTOFF; this catches anything stricter.
        docResults = docResults.filter((r: any) => (r.score || 0) >= minScore);
      }

      // Build chunk highlights and nav points from the API results. The
      // backend already filtered by relevance + exact-match exemption; we
      // just need to flatten bboxes per chunk and SORT BY DOCUMENT POSITION
      // so that Next/Prev navigation goes top-to-bottom through the doc
      // rather than relevance-first.
      type ChunkData = { highlights: HighlightBox[]; navAnchor: HighlightBox };
      const chunks: ChunkData[] = [];
      docResults.forEach((result: any) => {
        const chunkBoxes: HighlightBox[] = [];
        if (result.bbox && Array.isArray(result.bbox)) {
          result.bbox.forEach((bboxItem: any) => {
            const parsed = parseBBoxItem(bboxItem, result.page_num);
            if (parsed) {
              chunkBoxes.push({ page: parsed.page, bbox: parsed.bbox, text: result.text });
            }
          });
        }
        if (chunkBoxes.length === 0) return;
        // Sort within-chunk so the topmost bbox is the nav anchor.
        chunkBoxes.sort((a, b) =>
          a.page !== b.page ? a.page - b.page : b.bbox.t - a.bbox.t
        );
        chunks.push({ highlights: chunkBoxes, navAnchor: chunkBoxes[0] });
      });

      // Sort across chunks by document position (page asc, then top-to-
      // bottom — PDF y-axis: larger t = higher on page).
      chunks.sort((a, b) => {
        if (a.navAnchor.page !== b.navAnchor.page) {
          return a.navAnchor.page - b.navAnchor.page;
        }
        return b.navAnchor.bbox.t - a.navAnchor.bbox.t;
      });

      const allHighlights: HighlightBox[] = chunks.flatMap((c) => c.highlights);
      const chunkNavPoints: HighlightBox[] = chunks.map((c) => c.navAnchor);

      // Navigation points are the semantic chunks the retrieval API
      // returned, in reading order — one stop per chunk that holds content
      // relevant to the query. Literal text matches (e.g., the verbatim
      // phrase appearing in a figure caption that's not part of any chunk)
      // are intentionally NOT navigable: the counter "X of N" should reflect
      // chunks with semantic highlights, not every literal occurrence.
      // Within each navigated-to chunk, the LLM extracts and highlights the
      // relevant phrases on demand via the visibility-gated path.
      // findTextMatchesOnPage is kept (and tested) for potential future use.
      const navPoints = chunkNavPoints;

      console.log(
        `[In-PDF Search] ${docResults.length} semantic chunks → ${navPoints.length} nav points`
      );

      // Tear down all phrase-highlight state before applying new results so
      // any in-flight LLM calls for the previous query are aborted (their
      // late responses cannot paint into the new query's overlays).
      clearAllPhraseState();
      setInPdfSearchResults(navPoints);
      setHighlights(mergeSequentialHighlights(allHighlights));
      setCurrentMatchIndex(0);

      if (navPoints.length > 0) {
        hasSnappedToHighlight.current = false;
        goToPage(navPoints[0].page);
      }
    } catch (error) {
      console.error('In-PDF search error:', error);
    } finally {
      setIsSearching(false);
    }
  };

  // Navigate to next match
  const goToNextMatch = () => {
    if (inPdfSearchResults.length === 0) return;
    const nextIndex = (currentMatchIndex + 1) % inPdfSearchResults.length;
    setCurrentMatchIndex(nextIndex);
    const highlight = inPdfSearchResults[nextIndex];
    goToPage(highlight.page);
  };

  // Navigate to previous match
  const goToPrevMatch = () => {
    if (inPdfSearchResults.length === 0) return;
    const prevIndex = (currentMatchIndex - 1 + inPdfSearchResults.length) % inPdfSearchResults.length;
    setCurrentMatchIndex(prevIndex);
    const highlight = inPdfSearchResults[prevIndex];
    goToPage(highlight.page);
  };

  // Fetch TOC data
  const fetchTocData = async () => {
    setLoadingToc(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/document/${docId}?data_source=${dataSource}`);
      const doc = response.data as { toc_classified?: string; toc?: string };
      // Use toc_classified if available, otherwise fall back to toc
      const toc = doc.toc_classified || doc.toc || '';
      setDocumentToc(toc);
    } catch (error) {
      console.error('Error fetching TOC:', error);
      setDocumentToc('');
    } finally {
      setLoadingToc(false);
    }
  };

  // Render metadata
  const renderMetadata = () => {
    // Only exclude chunk text and internal fields - show everything else
    const excludeFields = [
      'text',                // Too long to display
      'semanticMatches',     // Internal highlighting data
      'bbox',                // Complex coordinate data, not user-friendly
      'metadata'             // Don't show nested metadata object if it exists
    ];

    const metadataFields = Object.entries(metadata)
      .filter(([key, value]) => {
        // Filter out excluded fields
        if (excludeFields.includes(key)) return false;
        // Filter out null, undefined, or empty string values
        if (value === null || value === undefined || value === '') return false;
        // Filter out empty arrays or objects
        if (Array.isArray(value) && value.length === 0) return false;
        return !(typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0);
      })
      .sort(([keyA], [keyB]) => keyA.localeCompare(keyB));

    if (metadataFields.length === 0) {
      return <div className="metadata-content">No additional metadata available</div>;
    }

    return (
      <div className="metadata-content">
        {metadataFields.map(([key, value]) => (
          <div key={key} className="metadata-field">
            <span className="metadata-key">{key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:</span>
            <span className="metadata-value">
              {/* Handle different value types */}
              {key === 'headings' && Array.isArray(value)
                ? value.join(' > ')
                : Array.isArray(value)
                  ? value.join(', ')
                  : typeof value === 'object'
                    ? JSON.stringify(value, null, 2)
                    : String(value)}
            </span>
          </div>
        ))}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="pdf-viewer-container">
        <div className="pdf-viewer-loading">Loading PDF...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="pdf-viewer-container">
        <div className="pdf-viewer-error">
          <p>{error}</p>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    );
  }

  const totalScrollHeight = totalPages * actualPageHeight;

  return (
    <div className="pdf-viewer-container">
      <div className="pdf-viewer-header">
        <div className="pdf-viewer-title-row">
          {pdfUrl ? (
            <a href={pdfUrl} target="_blank" rel="noopener noreferrer" title="Source document">
              <img
                src={`${API_BASE_URL}/document/${docId}/thumbnail?data_source=${dataSource}`}
                alt=""
                className="pdf-thumbnail"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
              />
            </a>
          ) : (
            <img
              src={`${API_BASE_URL}/document/${docId}/thumbnail?data_source=${dataSource}`}
              alt=""
              className="pdf-thumbnail"
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            />
          )}
          <h4 title={title}>{title}</h4>
          <button onClick={onClose} className="close-button">✕</button>
        </div>

        {/* Second row: badges, metadata */}
        <div className="pdf-viewer-badges-row">
          {organization && (
            <span className="badge badge-org">{organization}</span>
          )}
          {year && (
            <span className="badge badge-year">{year}</span>
          )}
          <span className="badge badge-page">Page {pageNum}</span>
          {webUrl && (
            <a href={webUrl} target="_blank" rel="noopener noreferrer" className="pdf-badge-link" title="Hosting page for the document">
              {dataSource ? `${dataSource.toUpperCase()} Hosting Page` : 'Hosting Page'}
            </a>
          )}
          {pdfUrl && (
            <a href={pdfUrl} target="_blank" rel="noopener noreferrer" className="pdf-badge-link" title="Source document">
              {organization ? `${organization} Source Document` : 'Source Document'}
            </a>
          )}
          <button
            className="pdf-metadata-link"
            onClick={() => {
              if (!documentToc && !loadingToc) {
                fetchTocData();
              }
              setTocModalOpen(true);
            }}
            style={{ marginLeft: 'auto' }}
          >
            Contents
          </button>
          <button
            className="pdf-metadata-link"
            onClick={() => {
              if (onOpenMetadata) {
                onOpenMetadata(metadata || {});
                return;
              }
              setMetadataExpanded(!metadataExpanded);
            }}
          >
            Metadata
          </button>
        </div>

        {/* Metadata section */}
        {!onOpenMetadata && metadataExpanded && renderMetadata()}

        <div className="pdf-viewer-controls">
          <button onClick={() => goToPage(currentPage - 1)} disabled={currentPage <= 1}>
            Previous
          </button>
          <span className="page-info">
            Page{' '}
            <input
              type="number"
              min="1"
              max={totalPages}
              value={currentPage}
              onChange={(e) => {
                const num = parseInt(e.target.value);
                if (!isNaN(num)) goToPage(num);
              }}
              className="page-input"
            />
            {' '}of {totalPages}
          </span>
          <button onClick={() => goToPage(currentPage + 1)} disabled={currentPage >= totalPages}>
            Next
          </button>
        </div>
        <div className="pdf-search-controls">
          <input
            type="text"
            placeholder="Search in document..."
            value={inPdfSearchQuery}
            onChange={(e) => setInPdfSearchQuery(e.target.value)}
            onKeyPress={(e) => {
              if (e.key === 'Enter') {
                performInPdfSearch(inPdfSearchQuery);
              }
            }}
            className="pdf-search-input"
          />
          <button
            onClick={() => performInPdfSearch(inPdfSearchQuery)}
            disabled={isSearching}
            className="pdf-search-button"
          >
            {isSearching ? (
              <>
                {Array.from('Searching...').map((char, i) => (
                  <span
                    key={i}
                    className="wave-char"
                    style={{ animationDelay: `${i * 0.1}s` }}
                  >
                    {char}
                  </span>
                ))}
              </>
            ) : (
              'Search'
            )}
          </button>
          {inPdfSearchResults.length > 0 && (
            <>
              <span className="search-results-info">
                {currentMatchIndex + 1} of {inPdfSearchResults.length}
              </span>
              <button onClick={goToPrevMatch} className="search-nav-button">
                ↑
              </button>
              <button onClick={goToNextMatch} className="search-nav-button">
                ↓
              </button>
            </>
          )}
        </div>
      </div>

      <div
        className="pdf-viewer-content"
        ref={scrollContainerRef}
        onScroll={handleScroll}
        style={{ overflowY: 'scroll' }}
      >
        <div
          ref={pagesContainerRef}
          style={{ height: `${totalScrollHeight}px`, position: 'relative' }}
        />

        {/* Floating Zoom Controls on PDF */}
        <div className="pdf-zoom-controls">
          <button
            onClick={handleZoomIn}
            className="pdf-zoom-button"
            title="Zoom In"
            aria-label="Zoom In"
          >
            +
          </button>
          <div className="pdf-zoom-level">{Math.round(scale * 100)}%</div>
          <button
            onClick={handleZoomOut}
            className="pdf-zoom-button"
            title="Zoom Out"
            aria-label="Zoom Out"
          >
            −
          </button>
          <button
            onClick={handleResetZoom}
            className="pdf-zoom-button pdf-zoom-reset"
            title="Reset Zoom"
            aria-label="Reset Zoom"
          >
            ⟲
          </button>
        </div>
      </div>

      {/* Mobile-only Close Preview button */}
      <button onClick={onClose} className="mobile-close-preview-button">
        Close Preview
      </button>

      {/* TOC Modal */}
      <TocModal
        isOpen={tocModalOpen}
        onClose={() => setTocModalOpen(false)}
        toc={documentToc}
        docId={docId}
        dataSource={dataSource}
        loading={loadingToc}
        pdfUrl={pdfUrl}
        onTocUpdated={setDocumentToc}
        pageCount={totalPages}
        onPageSelect={(page) => {
          goToPage(page);
          setTocModalOpen(false);
        }}
      />
    </div>
  );
};
