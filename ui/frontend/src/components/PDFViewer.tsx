import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import API_BASE_URL, { PDF_SEMANTIC_HIGHLIGHTS } from '../config';
import { HighlightBox, SummaryModelConfig } from '../types/api';
import { findAllMatches, findSemanticMatches } from '../utils/textHighlighting';
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
  recencyBoostEnabled?: boolean;
  recencyWeight?: number;
  recencyScaleDays?: number;
  sectionTypes?: string[];
  keywordBoostShortQueries?: boolean;
  minChunkSize?: number;
  minScore?: number;
  rerankModel?: string | null;
  searchModel?: string | null;
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

const normalizePdfText = (text: string): string =>
  text
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

const normalizePdfTextNoSpaces = (text: string): string =>
  text
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
    highlightOverlay.style.zIndex = '5';
    container.appendChild(highlightOverlay);
  });
};

type CharMapping = { itemIdx: number; charIdx: number };

const buildPageTextMap = (items: any[]): { fullText: string; charMap: CharMapping[] } => {
  let fullText = '';
  const charMap: CharMapping[] = [];
  for (let i = 0; i < items.length; i++) {
    const str = items[i].str || '';
    for (let c = 0; c < str.length; c++) {
      charMap.push({ itemIdx: i, charIdx: c });
    }
    fullText += str;
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
  const cw = item.str.length > 0 ? iw / item.str.length : 0;
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

const findTextMatchesOnPage = (
  items: any[],
  searchTerm: string,
  pageNum: number
): HighlightBox[] => {
  if (items.length === 0) return [];

  const { fullText, charMap } = buildPageTextMap(items);
  const lowerText = fullText.toLowerCase();
  const matches: HighlightBox[] = [];
  let pos = 0;

  while ((pos = lowerText.indexOf(searchTerm, pos)) !== -1) {
    const endPos = pos + searchTerm.length - 1;
    if (endPos >= charMap.length) break;

    const bbox = computeMatchBBox(items, charMap[pos], charMap[endPos]);
    if (bbox) {
      matches.push({
        page: pageNum,
        bbox,
        text: fullText.substring(pos, pos + searchTerm.length),
        isTextMatch: true
      });
    }
    pos += 1;
  }

  return matches;
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
  dataSource = 'uneg',
  semanticHighlightModelConfig,
  onOpenMetadata,
  searchDenseWeight = 0.8,
  rerankEnabled = true,
  recencyBoostEnabled = false,
  recencyWeight = 0.15,
  recencyScaleDays = 365,
  sectionTypes = [],
  keywordBoostShortQueries = true,
  minChunkSize = 100,
  minScore = 0,
  rerankModel = null,
  searchModel = null,
}) => {
  // Extract fields from metadata
  const webUrl = metadata.report_url;
  const pdfUrl = metadata.pdf_url;
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
  const processedBBoxesRef = useRef<Set<string>>(new Set()); // Track which bboxes have been semantically highlighted

  // Calculate scale based on viewport width for mobile
  useEffect(() => {
    const updateScale = () => setScale(getResponsiveScale());
    updateScale();
    window.addEventListener('resize', updateScale);
    return () => window.removeEventListener('resize', updateScale);
  }, []);

  // Reset snap state when document/chunk changes
  useEffect(() => {
    hasSnappedToHighlight.current = false;
    processedBBoxesRef.current.clear(); // Clear processed bboxes when doc/chunk/page changes
    // Always enable programmatic scrolling when doc/chunk/page changes
    isScrollingProgrammatically.current = true;
    // Clear in-PDF search results when opening a new document
    setInPdfSearchResults([]);
    setInPdfSearchQuery('');
    setCurrentMatchIndex(0);
  }, [docId, chunkId, pageNum]);

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
      console.log(`[Highlights] Setting ${immediateHighlights.length} IMMEDIATE bbox highlights with text`);
      setHighlights(immediateHighlights);
    }

    // Then load additional highlights asynchronously if needed (and we don't already have bbox highlights)
    if (chunkId && pdfDoc && initialBBox.length === 0) {
      loadHighlights();
    }
  }, [chunkId, pdfDoc, initialBBox, inPdfSearchQuery, inPdfSearchResults]);

  // Render visible pages when current page changes
  useEffect(() => {
    if (pdfDoc && currentPage > 0) {
      renderVisiblePages(false);
    }
  }, [pdfDoc, currentPage, totalPages]);

  // Re-render visible pages when search results change (but not on every highlight change to avoid flickering)
  useEffect(() => {
    if (pdfDoc && currentPage > 0 && inPdfSearchResults.length > 0) {
      // Clear rendered pages to force re-render with new search highlights
      setRenderedPages(new Map());
      renderVisiblePages(true);
    }
  }, [inPdfSearchResults.length]); // Only re-render when search result count changes

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

    let targetScroll = (currentPage - 1) * actualPageHeight;
    let shouldScroll = false;

    // Calculate highlight offset if available
    let highlightOffset = 0;
    const targetHighlight = getTargetHighlight(pageHighlights);
    if (targetHighlight) {
      // The viewport height in PDF units (unscaled)
      // actualPageHeight includes margin, so we need to remove it and divide by scale
      const viewportHeightPdfUnits = (actualPageHeight - 20) / scale;

      // Calculate y position from top of page (same formula as in renderPage)
      // This gives us the pixel offset from the top of the page container
      highlightOffset = (viewportHeightPdfUnits - targetHighlight.bbox.t) * scale;

      // Add some padding (e.g. 100px) so it's not right at the edge
      // On mobile, use less padding since screen is smaller
      const padding = window.innerWidth <= 640 ? 50 : 100;
      highlightOffset = Math.max(0, highlightOffset - padding);
    }

    // IMMEDIATE scroll when programmatic flag is set (opening new doc/chunk/page)
    // Don't wait for highlights - scroll to page immediately
    if (isScrollingProgrammatically.current) {
      shouldScroll = true;
      // If highlights are already available, use them; otherwise just scroll to page top
      if (pageHighlights.length > 0) {
        targetScroll += highlightOffset;
        hasSnappedToHighlight.current = true;
        console.log(`[Scroll] IMMEDIATE scroll to page ${currentPage} WITH highlights at ${targetScroll}px`);
      } else {
        console.log(`[Scroll] IMMEDIATE scroll to page ${currentPage} at ${targetScroll}px (highlights will adjust later)`);
        // Don't mark as snapped yet - let the secondary scroll happen when highlights load
        // hasSnappedToHighlight.current stays false
      }
      isScrollingProgrammatically.current = false;
    }
    // SECONDARY scroll when highlights load after initial page scroll
    else if (!hasSnappedToHighlight.current && pageHighlights.length > 0) {
      // Highlights just loaded - adjust scroll position to show them
      targetScroll += highlightOffset;
      shouldScroll = true;
      hasSnappedToHighlight.current = true;
      console.log(`[Scroll] ADJUSTING scroll for ${pageHighlights.length} highlights to ${targetScroll}px`);
    }

    if (shouldScroll) {
      lastProgrammaticScrollTime.current = Date.now();
      // Use setTimeout to ensure all rendering is complete before scrolling
      setTimeout(() => {
        requestAnimationFrame(() => {
          if (scrollContainerRef.current) {
            scrollContainerRef.current.scrollTop = targetScroll;
          }
        });
      }, 100); // Reduced delay for faster initial scroll
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

      // Merge with existing immediate highlights (avoid duplicates)
      setHighlights(prevHighlights => {
        const existingPages = new Set(prevHighlights.map(h => `${h.page}-${h.bbox.l}-${h.bbox.t}`));
        const newHighlights = apiHighlights.filter(h =>
          !existingPages.has(`${h.page}-${h.bbox.l}-${h.bbox.t}`)
        );
        console.log(`[Highlights] Adding ${newHighlights.length} new highlights (${prevHighlights.length} already present)`);
        return [...prevHighlights, ...newHighlights];
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

      // Render chunk highlights (always render these, even if text layer highlighting fails)
      // Draw bounding boxes AFTER text layer is transparent (like test script)
      console.log(`[Chunk Highlights] Rendering ${pageHighlights.length} chunk highlights for page ${pageNumber}`);
      pageHighlights.forEach(highlight => {
        const { bbox } = highlight;
        const scale = viewport.scale;
        const x = bbox.l * scale;
        const y = (viewport.height / scale - bbox.t) * scale;
        const width = (bbox.r - bbox.l) * scale;
        const height = (bbox.t - bbox.b) * scale;

        // Add padding margin (5px on each side)
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
        div.title = highlight.text.substring(0, 100);
        pageContainer.appendChild(div);

        // Add a vertical indicator line on the right edge of the page
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
      });

      console.log(`[Text Layer]Page ${pageNumber}: searchQuery = '${effectiveSearchQuery}', inPdfSearchQuery = '${inPdfSearchQuery}', highlights = ${pageHighlights.length}`);
      // Highlight matching text in text layer (if search query exists)
      // IMPORTANT: Only highlight text that falls within the chunk bounding boxes
      if (effectiveSearchQuery && effectiveSearchQuery.trim() && pageHighlights.length > 0) {
        console.log(`[Text Layer] Starting text layer highlighting for page ${pageNumber} with query: "${effectiveSearchQuery}"`);

        // Get all text spans in the text layer
        const textSpans = textLayer.querySelectorAll('span');
        console.log('[Text Layer] Text spans found:', textSpans.length);

        if (textSpans.length === 0) {
          console.warn('[Text Layer] No text spans found! Text layer may not be ready.');
          return;
        }

        // For each chunk highlight, find and highlight matching text within its bounding box
        pageHighlights.forEach(highlight => {
          const { bbox, text: chunkText } = highlight;
          console.log(`[Text Layer] Processing highlight: bbox=${JSON.stringify(bbox)}, chunkText length=${chunkText?.length || 0}`);

          // Convert bbox to viewport coordinates
          const bboxLeft = bbox.l * scale;
          const bboxRight = bbox.r * scale;
          const bboxTop = (viewport.height / scale - bbox.t) * scale;
          const bboxBottom = (viewport.height / scale - bbox.b) * scale;

          console.log(`[Text Layer] Processing chunk bbox: left = ${bboxLeft}, right = ${bboxRight}, top = ${bboxTop}, bottom = ${bboxBottom} `);

          // Find all spans that fall within this bounding box
          const spansInBox: HTMLElement[] = [];
          textSpans.forEach(span => {
            const spanElement = span as HTMLElement;
            const spanRect = spanElement.getBoundingClientRect();
            const containerRect = pageContainer.getBoundingClientRect();

            // Get span position relative to page container
            const spanLeft = spanRect.left - containerRect.left;
            const spanRight = spanRect.right - containerRect.left;
            const spanTop = spanRect.top - containerRect.top;
            const spanBottom = spanRect.bottom - containerRect.top;

            // Check if span overlaps with bounding box
            const overlaps = !(spanRight < bboxLeft || spanLeft > bboxRight ||
              spanBottom < bboxTop || spanTop > bboxBottom);

            if (overlaps) {
              spansInBox.push(spanElement);
            }
          });

          console.log(`[Text Layer] Found ${spansInBox.length} spans within chunk bbox`);

          if (spansInBox.length === 0) {
            return;
          }

          // Use chunk text from database (same as search results) for semantic matching
          // This ensures we get the EXACT same semantic matches as search results
          const bboxText = chunkText || '';

          if (!bboxText) {
            console.log(`[Text Layer] No chunk text available for bbox, skipping semantic highlighting`);
            return;
          }

          // Build text from PDF spans (for matching phrases in PDF)
          const pdfText = spansInBox.map(span => span.textContent || '').join('');

          console.log(`[Text Layer] Chunk text length: ${bboxText.length} chars`);
          console.log(`[Text Layer] PDF box text length: ${pdfText.length} chars`);

          // Run semantic matching on chunk text - ONLY ONCE per bbox (ONLY if feature is enabled)
          // Create unique key for this bbox to prevent re-running on re-renders
          const bboxKey = `${pageNumber}-${bbox.l}-${bbox.t}-${bbox.r}-${bbox.b}`;

          if (!PDF_SEMANTIC_HIGHLIGHTS) {
            console.log(`[Text Layer] PDF_SEMANTIC_HIGHLIGHTS is disabled, skipping semantic matching`);
            return;
          }

          if (processedBBoxesRef.current.has(bboxKey)) {
            console.log(`[Text Layer] BBox ${bboxKey} already processed, skipping semantic matching`);
            return;
          }

          // Mark as processed IMMEDIATELY to prevent duplicate calls
          processedBBoxesRef.current.add(bboxKey);

          // Run semantic matching in background - ONCE
          (async () => {
            try {
              console.log(`[Text Layer] [BBox ${bboxKey}] Starting ONE-TIME semantic matching with query: "${effectiveSearchQuery}"`);
              const semanticMatches = await findSemanticMatches(
                bboxText,
                effectiveSearchQuery,
                0.4,
                semanticHighlightModelConfig
              );
              console.log(`[Text Layer] [BBox ${bboxKey}] Found ${semanticMatches.length} semantic matches`);

              if (semanticMatches.length === 0) {
                return;
              }

              // Get current page container
              const currentPageContainer = document.getElementById(`pdf-page-${pageNumber}`) as HTMLDivElement;
              if (!currentPageContainer) {
                console.log(`[Text Layer] [BBox ${bboxKey}] Page container ${pageNumber} no longer exists`);
                return;
              }

              // Clear existing overlays for THIS bbox only
              const oldOverlays = currentPageContainer.querySelectorAll(`.phrase-highlight-overlay[data-bbox="${bboxKey}"]`);
              oldOverlays.forEach(overlay => overlay.remove());

              // Use the spans we already found (spansInBox) - these are within the bounding box
              // Build PDF text from these spans for matching
              const pdfTextForMatching = spansInBox.map(span => span.textContent || '').join('');
              const normalizedPdfText = normalizePdfText(pdfTextForMatching);

              semanticMatches.forEach((match, phraseIdx) => {
                const phrase = match.matchedText;
                const range = findPhraseRange(normalizedPdfText, pdfTextForMatching, phrase);
                if (!range) {
                  console.log(`[Text Layer] ✗ Phrase ${phraseIdx + 1} NOT FOUND in PDF text`);
                  return;
                }

                console.log(
                  `[Text Layer] Phrase ${phraseIdx + 1} (${range.normalizedPhrase.length} chars): "${range.normalizedPhrase.substring(0, 80)}..."`
                );

                const spanMap = buildSpanMap(spansInBox);
                const matchedSpans = findMatchedSpans(spanMap, range.start, range.end);
                if (matchedSpans.length === 0) {
                  return;
                }

                const sortedSpans = sortSpansByPosition(matchedSpans);
                const containerRect = currentPageContainer.getBoundingClientRect();
                const spanGroups = groupSpansByLine(sortedSpans, containerRect);
                appendSpanGroups(spanGroups, currentPageContainer, bboxKey, range.overlayColor);

                console.log(
                  `[Text Layer] ✓ Matched phrase ${phraseIdx + 1}: "${phrase.substring(0, 60)}..." (${sortedSpans.length} spans, ${spanGroups.length} continuous overlay${spanGroups.length > 1 ? 's' : ''})`
                );
              });

              console.log(`[Text Layer] [BBox ${bboxKey}] ✅ ONE-TIME highlighting complete with ${semanticMatches.length} matches`);
            } catch (error) {
              console.error(`[Text Layer] [BBox ${bboxKey}] Semantic matching failed:`, error);
              // Remove from processed set so it can be retried if needed
              processedBBoxesRef.current.delete(bboxKey);
            }
          })();
        });
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
      return;
    }

    setIsSearching(true);
    try {
      // --- Semantic search via API ---
      const params: any = {
        q: query,
        limit: 100,
        title: title,
        data_source: dataSource,
        dense_weight: searchDenseWeight.toString(),
        rerank: rerankEnabled.toString(),
        recency_boost: recencyBoostEnabled.toString(),
        recency_weight: recencyWeight.toString(),
        recency_scale_days: recencyScaleDays.toString(),
        keyword_boost_short_queries: keywordBoostShortQueries.toString(),
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
      if (searchModel) {
        params.model = searchModel;
      }

      const response = await axios.get(`${API_BASE_URL}/search`, { params });
      const data = response.data as { results?: any[] };
      let docResults = data.results || [];
      if (minScore > 0) {
        docResults = docResults.filter((r: any) => (r.score || 0) >= minScore);
      }

      // Build all bbox highlights AND one navigation point per chunk
      const allHighlights: HighlightBox[] = [];
      const chunkNavPoints: HighlightBox[] = [];

      docResults.forEach((result: any) => {
        const chunkBoxes: HighlightBox[] = [];
        if (result.bbox && Array.isArray(result.bbox)) {
          result.bbox.forEach((bboxItem: any) => {
            const parsed = parseBBoxItem(bboxItem, result.page_num);
            if (parsed) {
              const h: HighlightBox = { page: parsed.page, bbox: parsed.bbox, text: result.text };
              chunkBoxes.push(h);
              allHighlights.push(h);
            }
          });
        }
        if (chunkBoxes.length > 0) {
          // Pick the topmost bbox on the earliest page as navigation point
          chunkBoxes.sort((a, b) => a.page !== b.page ? a.page - b.page : b.bbox.t - a.bbox.t);
          chunkNavPoints.push(chunkBoxes[0]);
        }
      });

      // --- Local text matches for literal keyword hits ---
      const textNavPoints: HighlightBox[] = [];
      if (pdfDoc) {
        const searchTerm = query.toLowerCase();
        for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
          const page = await pdfDoc.getPage(pageNum);
          const textContent = await page.getTextContent();
          const textMatches = findTextMatchesOnPage(textContent.items, searchTerm, pageNum);
          textMatches.forEach(m => {
            allHighlights.push(m);
            textNavPoints.push(m);
          });
        }
      }

      // Navigation: use literal text matches if any, otherwise fall back to semantic chunks
      const navPoints = textNavPoints.length > 0 ? textNavPoints : chunkNavPoints;

      console.log(`[In-PDF Search] ${docResults.length} API chunks, ${textNavPoints.length} text matches, ${allHighlights.length} total highlights`);

      setInPdfSearchResults(navPoints);
      setHighlights(allHighlights);
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
          <h4 title={title}>{title}</h4>
          <div className="pdf-viewer-links">
            {(webUrl || pdfUrl) && (
              <>
                {webUrl && (
                  <a href={webUrl} target="_blank" rel="noopener noreferrer" className="doc-link">
                    Web
                  </a>
                )}
                {pdfUrl && (
                  <a href={pdfUrl} target="_blank" rel="noopener noreferrer" className="doc-link">
                    PDF
                  </a>
                )}
              </>
            )}
          </div>
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
