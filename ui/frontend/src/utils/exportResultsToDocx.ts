/**
 * Client-side generator for a nicely-formatted Word (.docx) export of a
 * search result set, including the AI summary.
 *
 * The export is produced in the browser using the `docx` package. The only
 * backend round-trip is fetching the table / figure screenshots shown on
 * screen (from `<fileBaseUrl>/file/<path>`) so they can be embedded in the
 * document; with no `fileBaseUrl` the export is fully client-side and
 * text-only. The resulting Blob can be handed to `file-saver`'s `saveAs` for
 * download.
 *
 * Design goals (see also the unit tests):
 *  - Cover page with query, dataset, timestamp, and result count.
 *  - AI summary with markdown-aware headings / bullets / emphasis.
 *  - One "card" per result: clickable title, metadata line, breadcrumb of
 *    headings, and the FULL excerpt (never truncated).
 *  - Every document title is a working hyperlink (pdf_url when available,
 *    otherwise the canonical evidencelab.ai deep-link).
 */
import {
  AlignmentType,
  Bookmark,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  FootnoteReferenceRun,
  HeadingLevel,
  ImageRun,
  InternalHyperlink,
  LevelFormat,
  Packer,
  PageBreak,
  PageNumber,
  Paragraph,
  ShadingType,
  TextRun,
  convertInchesToTwip,
} from 'docx';
import type { ChunkElement, SearchResult } from '../types/api';
import {
  buildOrderedElements,
  isTextRedundantWithTable,
} from '../components/searchResultCardUtils';
import {
  buildCitationSequenceMap,
  buildGroupedReferences,
  parseCitationNumbers,
  type DocumentGroup,
} from './citations';

export interface ExportOptions {
  query: string;
  aiSummary?: string;
  results: SearchResult[];
  dataSource?: string;
  /** Public origin of the deployed Evidence Lab — used to build fallback
   *  hyperlinks when a result has no pdf_url. Defaults to window.location.origin
   *  at runtime. Overridable for tests. */
  siteOrigin?: string;
  /** Injectable clock for deterministic tests. */
  now?: () => Date;
  /** Heading for the per-result excerpts section (default "Search Results").
   *  The Brief export passes "Reference Excerpts". */
  resultsSectionTitle?: string;
  // Render a compact references list (no excerpts) instead of full result
  // cards, mirroring the Brief's on-screen References section. 'grouped'
  // collapses to one row per document.
  referenceList?: 'flat' | 'grouped';
  /** Cover-page document title (default "Evidence Lab — Search Export").
   *  The Brief export passes "AI-generated Research Brief". */
  documentTitle?: string;
  /** Heading for the AI-prose section (default "AI Summary"). The Brief export
   *  passes the brief topic so the prose sits under its own subject heading. */
  summaryHeading?: string;
  /** Optional disclaimer rendered as a bordered call-out box on the cover,
   *  directly under the metadata line. The Brief export uses it to flag that
   *  the content is AI-generated and must be verified. */
  infoBox?: string;
  /** When true, insert a clickable Table of Contents after the cover. It is
   *  built from real content (internal links to heading bookmarks), not a Word
   *  field, so opening the document never prompts to update fields. */
  tableOfContents?: boolean;
  /** Base URL of the file-serving API (e.g. "/api"), used to fetch the table /
   *  figure screenshots shown on screen so they can be embedded in the export.
   *  When omitted, no screenshots are fetched and the export is text-only —
   *  this preserves the prior behaviour and keeps SSR / unit tests that don't
   *  exercise images simple. */
  fileBaseUrl?: string;
  /** Injectable fetch implementation for deterministic tests. Defaults to the
   *  global `fetch` (bound to `globalThis`). */
  fetchFn?: typeof fetch;
  /** How inline `[N]` citation markers are rendered in the prose:
   *  - `'links'` (default): each `[N]` stays an inline bracketed hyperlink to
   *    the cited source, matching the on-screen render.
   *  - `'footnotes'`: each `[N]` becomes a Word footnote reference, and the
   *    source (title, page, PDF link) is placed as a footnote on the same
   *    page. The end References/excerpt sections are still included. */
  citationStyle?: 'links' | 'footnotes';
}

/** MIME type for a .docx file — exported so the call-site can set it on Blobs
 *  and tests can assert it. */
export const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Slugify a query into a safe filename fragment. */
const slugify = (s: string): string =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'search';

/** Build a filename like "evidencelab-search-<slug>-<YYYYMMDD-HHMM>.docx" */
export const buildExportFilename = (query: string, now: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0');
  const stamp =
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `-${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `evidencelab-search-${slugify(query)}-${stamp}.docx`;
};

/** Append a `#page=N` fragment to a URL, replacing any existing one.
 *
 *  Adobe Reader, Chrome's built-in PDF viewer, and most web report viewers
 *  honour the `#page=N` fragment to jump straight to the cited page — that's
 *  the same fragment the SPA uses internally, and it lets readers click
 *  through directly to the cited page rather than to the document cover. */
const withPageAnchor = (url: string, pageNum: number | undefined): string => {
  const trimmed = url.replace(/#page=\d+$/, '');
  if (typeof pageNum !== 'number' || !Number.isFinite(pageNum)) return trimmed;
  return `${trimmed}#page=${pageNum}`;
};

/** Best-effort resolution of a clickable hyperlink for a result. */
export const resolveResultLink = (
  r: SearchResult,
  siteOrigin: string,
  dataSource?: string,
): string => {
  const directPdf =
    r.pdf_url ||
    r.metadata?.pdf_url ||
    r.metadata?.map_pdf_url ||
    r.metadata?.src_doc_raw_metadata?.pdf_url;
  if (typeof directPdf === 'string' && directPdf.trim()) {
    return withPageAnchor(directPdf.trim(), r.page_num);
  }
  const report = r.report_url;
  if (typeof report === 'string' && report.trim()) {
    return withPageAnchor(report.trim(), r.page_num);
  }

  const ds = dataSource || r.data_source || '';
  const page = typeof r.page_num === 'number' ? `#page=${r.page_num}` : '';
  const origin = siteOrigin.replace(/\/+$/, '');
  const query = ds ? `?data_source=${encodeURIComponent(ds)}` : '';
  return `${origin}/document/${r.doc_id}${query}${page}`;
};

/** Trim a block of text by (a) collapsing 3+ consecutive newlines into 2 and
 *  (b) trimming trailing whitespace on each line. Never truncates. */
const normaliseExcerpt = (s: string): string =>
  s
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) => line.replace(/[ \t]+$/g, ''))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

/** Inline children of a Paragraph: plain runs, hyperlink containers, or (in
 *  footnote mode) footnote reference marks. `Paragraph.children` accepts all
 *  three, so we expose this union. */
type InlineChild = TextRun | ExternalHyperlink | FootnoteReferenceRun;

/** Collects Word footnotes as the prose is rendered. Each cited `[N]` marker
 *  calls {@link FootnoteRegistry.add} to register a footnote (numbered by Word
 *  in appearance order) and gets back its id for a {@link FootnoteReferenceRun}.
 *  The accumulated `map` is handed to the `Document` `footnotes` option. */
export interface FootnoteRegistry {
  map: Record<string, { children: Paragraph[] }>;
  add: (result: SearchResult, siteOrigin: string, dataSource?: string) => number;
}

/** Build a footnote content paragraph for a cited result: the document title
 *  and page as text, followed by a clickable link to the actual PDF so a reader
 *  can open the source straight from the footnote. */
const buildFootnoteParagraph = (
  result: SearchResult,
  siteOrigin: string,
  dataSource?: string,
): Paragraph => {
  const title = result.title || result.document_title || 'Untitled';
  const meta: string[] = [];
  if (result.organization) meta.push(String(result.organization));
  if (result.year) meta.push(String(result.year));
  if (typeof result.page_num === 'number') meta.push(`p.${result.page_num}`);
  const label = title + (meta.length ? ` — ${meta.join(', ')}` : '') + '. ';
  return new Paragraph({
    children: [
      new TextRun({ text: label, size: 18 }),
      new ExternalHyperlink({
        link: resolveResultLink(result, siteOrigin, dataSource),
        children: [new TextRun({ text: 'Open PDF ›', style: 'Hyperlink', size: 18 })],
      }),
    ],
  });
};

/** Create an empty footnote registry with an auto-incrementing id counter.
 *  Word renders footnote markers in document order, so ids need only be unique
 *  and stable; we start at 1 and never reuse (repeated citations of the same
 *  source produce distinct footnotes, which is conventional footnote style). */
const createFootnoteRegistry = (): FootnoteRegistry => {
  const map: Record<string, { children: Paragraph[] }> = {};
  let nextId = 1;
  return {
    map,
    add(result, siteOrigin, dataSource) {
      const id = nextId++;
      map[String(id)] = {
        children: [buildFootnoteParagraph(result, siteOrigin, dataSource)],
      };
      return id;
    },
  };
};

/** Optional context that lets {@link inlineRuns} convert `[N]` markers in a
 *  body paragraph into clickable hyperlinks pointing at the cited result's
 *  source PDF / report — so a reader can click straight from the citation to
 *  the supporting page. */
export interface CitationContext {
  results: SearchResult[];
  siteOrigin: string;
  dataSource?: string;
  /** Maps each original `[N]` to its sequential display number, so inline
   *  citations render the same renumbered value as the on-screen summary and
   *  the References section. Built once from the full summary text. */
  sequenceMap: Map<number, number>;
  /** When present, `[N]` markers render as Word footnote references registered
   *  here (footnote mode) instead of inline bracketed hyperlinks. */
  footnotes?: FootnoteRegistry;
}

/** Build the inline children for a `[N]` / `[N, M]` citation marker. Each
 *  number becomes its own hyperlink so a reader can click any one of them
 *  to jump to the specific cited document/page. The brackets and commas
 *  remain as plain text so the visual matches the source markdown. */
const buildCitationRuns = (
  matched: string,
  base: { size?: number },
  ctx: CitationContext,
): InlineChild[] => {
  // Footnote mode: each valid `[N]` becomes a footnote reference mark (Word
  // auto-numbers them in appearance order); the source detail lives in the
  // footnote itself, so no brackets or inline numbers are emitted.
  if (ctx.footnotes) {
    const out: InlineChild[] = [];
    for (const n of parseCitationNumbers(matched)) {
      if (ctx.sequenceMap.get(n) === undefined) continue;
      const result = ctx.results[n - 1];
      if (!result) continue;
      // Separate consecutive footnote marks with a (superscript) space so
      // multiple citations after one sentence read as "¹ ²", not "¹²".
      if (out.length) out.push(new TextRun({ text: ' ', superScript: true }));
      const id = ctx.footnotes.add(result, ctx.siteOrigin, ctx.dataSource);
      out.push(new FootnoteReferenceRun(id));
    }
    return out;
  }
  const out: InlineChild[] = [new TextRun({ text: '[', size: base.size })];
  let rendered = 0;
  for (const n of parseCitationNumbers(matched)) {
    // Render the sequential (renumbered) value so the inline marker matches
    // the on-screen summary and this document's own References section. A
    // number absent from the sequence map is not a real citation — mirror the
    // on-screen renderer and drop it rather than show a misleading number.
    const sequential = ctx.sequenceMap.get(n);
    if (sequential === undefined) continue;
    if (rendered > 0) out.push(new TextRun({ text: ', ', size: base.size }));
    rendered += 1;
    const display = String(sequential);
    const result = ctx.results[n - 1];
    if (!result) {
      out.push(new TextRun({ text: display, size: base.size }));
      continue;
    }
    // The hyperlink still targets the original cited result.
    out.push(
      new ExternalHyperlink({
        link: resolveResultLink(result, ctx.siteOrigin, ctx.dataSource),
        children: [
          new TextRun({ text: display, style: 'Hyperlink', size: base.size }),
        ],
      }),
    );
  }
  out.push(new TextRun({ text: ']', size: base.size }));
  return out;
};

/** Render inline markdown emphasis (`**bold**`, `*italic*`, `` `code` ``) and,
 *  when a citation context is supplied, `[N]` / `[N, M]` citation markers
 *  into a list of inline children. Keeps the implementation tiny — we do not
 *  need a full markdown parser, just enough to survive what the AI summary
 *  endpoint emits. */
const inlineRuns = (
  text: string,
  base: { size?: number } = {},
  citations?: CitationContext,
): InlineChild[] => {
  const out: InlineChild[] = [];
  // Match **bold** | *italic* | `code` | [N(, M)*]
  const re = /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[(\d+(?:,\s*\d+)*)\])/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) {
      out.push(new TextRun({ text: text.slice(lastIndex, m.index), size: base.size }));
    }
    if (m[2] !== undefined) {
      out.push(new TextRun({ text: m[2], bold: true, size: base.size }));
    } else if (m[3] !== undefined) {
      out.push(new TextRun({ text: m[3], italics: true, size: base.size }));
    } else if (m[4] !== undefined) {
      out.push(new TextRun({ text: m[4], font: 'Menlo', size: base.size }));
    } else if (m[5] !== undefined && citations) {
      out.push(...buildCitationRuns(m[5], base, citations));
    } else {
      // No citation context — preserve the original `[N]` text verbatim.
      out.push(new TextRun({ text: m[0], size: base.size }));
    }
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    out.push(new TextRun({ text: text.slice(lastIndex), size: base.size }));
  }
  return out.length ? out : [new TextRun({ text, size: base.size })];
};

const HEADING_LEVELS_BY_DEPTH: Record<number, (typeof HeadingLevel)[keyof typeof HeadingLevel]> = {
  1: HeadingLevel.HEADING_1,
  2: HeadingLevel.HEADING_2,
  3: HeadingLevel.HEADING_3,
  4: HeadingLevel.HEADING_4,
  5: HeadingLevel.HEADING_5,
  6: HeadingLevel.HEADING_6,
};

/** Try to match a single markdown line to a "block" Paragraph (heading,
 *  bullet, or ordered list item). Returns null when the line is part of a
 *  plain paragraph buffer. Extracted from {@link markdownToParagraphs} to
 *  keep per-line complexity flat.
 *
 *  ``headingShift`` is added to the parsed depth so that markdown emitted
 *  inside the AI Summary section becomes a sub-heading (e.g. `#` becomes
 *  H2) rather than competing with the section's own H1. */
const matchBlockParagraph = (
  line: string,
  headingShift: number,
  citations?: CitationContext,
  bookmarkId?: string,
): Paragraph | null => {
  const h = /^(#{1,6})\s+(.*)$/.exec(line);
  if (h) {
    const depth = Math.min(6, Math.max(1, h[1].length + headingShift));
    const heading = HEADING_LEVELS_BY_DEPTH[depth] ?? HeadingLevel.HEADING_6;
    // Headings stay text-only — rendering hyperlinks inside a heading
    // confuses Word's outline view, so omit the citation context here. When a
    // bookmarkId is supplied, wrap the runs so the manual TOC can link here.
    const runs = inlineRuns(h[2]);
    return new Paragraph({
      heading,
      children: bookmarkId ? [new Bookmark({ id: bookmarkId, children: runs })] : runs,
      spacing: { before: 200, after: 120 },
    });
  }
  const ul = /^[-*]\s+(.*)$/.exec(line);
  if (ul) {
    return new Paragraph({
      children: inlineRuns(ul[1], {}, citations),
      bullet: { level: 0 },
      spacing: { after: 80 },
    });
  }
  const ol = /^(\d+)\.\s+(.*)$/.exec(line);
  if (ol) {
    return new Paragraph({
      children: inlineRuns(ol[2], {}, citations),
      numbering: { reference: 'summary-ordered', level: 0 },
      spacing: { after: 80 },
    });
  }
  return null;
};

/** Convert a markdown-ish AI summary into docx Paragraphs. Supports:
 *   - ATX headings `##`, `###`, `####`
 *   - Unordered list items `- ` or `* `
 *   - Ordered list items `1. `
 *   - Blank-line paragraph breaks
 *   - Inline **bold**, *italic*, `code`
 *  Anything more exotic is rendered as plain paragraph text — acceptable for
 *  a dev-mode export and safe against unexpected AI output.
 *
 *  ``headingShift`` lets callers demote any embedded headings — passing 1
 *  turns a top-level `#` into an H2 so it sits under the surrounding
 *  section's H1 rather than competing with it.
 *
 *  ``citations`` lets callers turn `[N]` markers in body text into clickable
 *  hyperlinks pointing at the cited result's source URL. */
export const markdownToParagraphs = (
  md: string,
  headingShift = 0,
  citations?: CitationContext,
  bookmarkPrefix?: string,
): Paragraph[] => {
  const paragraphs: Paragraph[] = [];
  const lines = md.replace(/\r\n/g, '\n').split('\n');

  let buffer: string[] = [];
  const flushParagraph = () => {
    const text = buffer.join(' ').trim();
    buffer = [];
    if (text) {
      paragraphs.push(
        new Paragraph({ children: inlineRuns(text, {}, citations), spacing: { after: 120 } }),
      );
    }
  };

  let headingIdx = 0;
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line === '') {
      flushParagraph();
      continue;
    }
    // Bookmark headings in document order so the manual TOC's links resolve.
    const bookmarkId =
      bookmarkPrefix && /^#{1,6}\s+/.test(line) ? `${bookmarkPrefix}${headingIdx++}` : undefined;
    const block = matchBlockParagraph(line, headingShift, citations, bookmarkId);
    if (block) {
      flushParagraph();
      paragraphs.push(block);
      continue;
    }
    buffer.push(line);
  }
  flushParagraph();
  return paragraphs;
};

/** Extract markdown headings (text + depth), in document order, for the TOC. */
const extractMarkdownHeadings = (md: string): { text: string; depth: number }[] => {
  const out: { text: string; depth: number }[] = [];
  for (const raw of md.replace(/\r\n/g, '\n').split('\n')) {
    const m = /^(#{1,6})\s+(.*)$/.exec(raw.trimEnd());
    if (m) out.push({ text: m[2].trim(), depth: m[1].length });
  }
  return out;
};

// ---------------------------------------------------------------------------
// Table / figure screenshots
//
// The on-screen search card renders any table or figure in a result as the
// low-resolution screenshot the pipeline extracted (served from
// `<fileBaseUrl>/file/<path>`). The text-only export mangled tables — a table's
// cell text was flattened into one paragraph. We now fetch those exact images
// and embed them with docx `ImageRun`, matching what the user sees on screen.
// ---------------------------------------------------------------------------

/** A screenshot fetched and ready for embedding. */
export interface FetchedImage {
  /** Raw image bytes. A `Uint8Array` (not a bare `ArrayBuffer`) is what docx's
   *  packer reliably embeds — it matches the `Buffer` shape `fs.readFileSync`
   *  yields in the library's own examples. */
  data: Uint8Array;
  /** docx-supported raster type, derived from the file extension. */
  type: 'png' | 'jpg' | 'gif' | 'bmp';
  /** Display size in px, already scaled to fit the page content width. */
  width: number;
  height: number;
}

/** Max embedded image width (~6 in at 96 dpi) so a screenshot fits the page
 *  content box without overflowing the margins. We never upscale past the
 *  image's natural width. */
const MAX_IMAGE_WIDTH_PX = 600;

/** File extension → docx raster type. A Map (not an object) sidesteps the
 *  `security/detect-object-injection` lint warning on dynamic key access. */
const IMAGE_TYPE_BY_EXT = new Map<string, FetchedImage['type']>([
  ['png', 'png'],
  ['jpg', 'jpg'],
  ['jpeg', 'jpg'],
  ['gif', 'gif'],
  ['bmp', 'bmp'],
]);

/** Strip a leading slash so the path matches the on-screen `<img>` src and can
 *  be appended to `<fileBaseUrl>/file/`. */
const normaliseImagePath = (p?: string): string | undefined => {
  const trimmed = p?.trim();
  if (!trimmed) return undefined;
  return trimmed.startsWith('/') ? trimmed.slice(1) : trimmed;
};

/** The screenshot path for a table/figure element (image_path for tables, path
 *  for figures) — identical to what the on-screen renderer uses. */
const visualElementPath = (el: ChunkElement): string | undefined =>
  normaliseImagePath(el.image_path || el.path);

/** The table/figure elements shown on screen for a result, in document order.
 *  Reuses the exact same selection/ordering as the search card so the export
 *  stays in lock-step with what the user sees. */
const visualElementsFor = (
  result: SearchResult,
): Array<ChunkElement & { key: string }> =>
  buildOrderedElements(result).filter(
    (el) => el.element_type === 'table' || el.element_type === 'image',
  );

/** docx image type for a path, or null for types `ImageRun` cannot embed
 *  (e.g. webp, svg). */
const imageTypeForPath = (path: string): FetchedImage['type'] | null => {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  return IMAGE_TYPE_BY_EXT.get(ext) ?? null;
};

/** Natural [width, height] from a PNG's IHDR header, or null. */
const pngDimensions = (view: DataView): [number, number] | null =>
  view.byteLength >= 24 && view.getUint32(0) === 0x89504e47
    ? [view.getUint32(16), view.getUint32(20)]
    : null;

/** Natural [width, height] from a JPEG SOF marker, or null. */
const jpegDimensions = (view: DataView): [number, number] | null => {
  if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) return null;
  let offset = 2;
  while (offset + 9 < view.byteLength) {
    if (view.getUint8(offset) !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = view.getUint8(offset + 1);
    const isSof =
      marker >= 0xc0 &&
      marker <= 0xcf &&
      marker !== 0xc4 &&
      marker !== 0xc8 &&
      marker !== 0xcc;
    if (isSof) return [view.getUint16(offset + 7), view.getUint16(offset + 5)];
    offset += 2 + view.getUint16(offset + 2);
  }
  return null;
};

/** Decode natural pixel dimensions from raw image bytes (PNG/JPEG). */
const naturalDimensions = (data: Uint8Array): [number, number] | null => {
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  return pngDimensions(view) ?? jpegDimensions(view);
};

/** Scale natural dimensions to fit {@link MAX_IMAGE_WIDTH_PX}, preserving the
 *  aspect ratio and never upscaling. */
const fitToPage = (w: number, h: number): { width: number; height: number } => {
  if (w <= 0 || h <= 0) {
    return { width: MAX_IMAGE_WIDTH_PX, height: Math.round(MAX_IMAGE_WIDTH_PX * 0.75) };
  }
  const width = Math.min(w, MAX_IMAGE_WIDTH_PX);
  return { width: Math.round(width), height: Math.round(h * (width / w)) };
};

/** Best available display size: the element's stored `image_size` (tables carry
 *  it), else dimensions decoded from the bytes (figures), else the bbox aspect
 *  ratio. */
const displaySizeFor = (
  el: ChunkElement,
  data: Uint8Array,
): { width: number; height: number } => {
  const size = el.image_size;
  if (Array.isArray(size) && size.length >= 2 && size[0] > 0 && size[1] > 0) {
    return fitToPage(size[0], size[1]);
  }
  const decoded = naturalDimensions(data);
  if (decoded) return fitToPage(decoded[0], decoded[1]);
  const bbox = el.bbox;
  if (Array.isArray(bbox) && bbox.length >= 4) {
    return fitToPage(bbox[2] - bbox[0], bbox[3] - bbox[1]);
  }
  return fitToPage(0, 0);
};

/** Fetch and decode a single screenshot. Returns null (and warns) when the
 *  image is missing, unfetchable, or an unembeddable type — the caller skips it
 *  and still produces the document, mirroring the on-screen `onError` that
 *  hides a broken thumbnail. */
const fetchVisualImage = async (
  el: ChunkElement,
  path: string,
  fileBaseUrl: string,
  fetchFn: typeof fetch,
): Promise<FetchedImage | null> => {
  const type = imageTypeForPath(path);
  if (!type) return null;
  try {
    const res = await fetchFn(`${fileBaseUrl.replace(/\/+$/, '')}/file/${path}`);
    if (!res.ok) return null;
    const data = new Uint8Array(await res.arrayBuffer());
    const { width, height } = displaySizeFor(el, data);
    return { data, type, width, height };
  } catch (err) {
    console.warn('Export to Word: could not fetch screenshot', path, err);
    return null;
  }
};

/** Fetch every table/figure screenshot shown across the result set, de-duped by
 *  path so each image is fetched once. Returns an empty map when no
 *  `fileBaseUrl` is configured (e.g. SSR / tests), leaving the export
 *  text-only. */
export const fetchResultImages = async (
  opts: ExportOptions,
): Promise<Map<string, FetchedImage>> => {
  const out = new Map<string, FetchedImage>();
  const { fileBaseUrl } = opts;
  if (!fileBaseUrl) return out;
  const fetchFn =
    opts.fetchFn ??
    (typeof fetch !== 'undefined' ? (fetch.bind(globalThis) as typeof fetch) : undefined);
  if (!fetchFn) return out;

  // De-dupe across results so each unique screenshot is fetched only once.
  const unique = new Map<string, ChunkElement>();
  for (const result of opts.results) {
    for (const el of visualElementsFor(result)) {
      const path = visualElementPath(el);
      if (path && !unique.has(path)) unique.set(path, el);
    }
  }
  await Promise.all(
    Array.from(unique.entries()).map(async ([path, el]) => {
      const img = await fetchVisualImage(el, path, fileBaseUrl, fetchFn);
      if (img) out.set(path, img);
    }),
  );
  return out;
};

/** Paragraphs embedding each successfully-fetched screenshot for a result, in
 *  document order. Images that failed to fetch are simply absent. */
const buildResultImageParagraphs = (
  result: SearchResult,
  images: Map<string, FetchedImage>,
): Paragraph[] => {
  const out: Paragraph[] = [];
  for (const el of visualElementsFor(result)) {
    const path = visualElementPath(el);
    const img = path ? images.get(path) : undefined;
    if (!img) continue;
    out.push(
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 120 },
        children: [
          new ImageRun({
            type: img.type,
            data: img.data,
            transformation: { width: img.width, height: img.height },
          }),
        ],
      }),
    );
  }
  return out;
};

/** True when an embedded table screenshot makes the chunk text redundant — we
 *  then drop the (mangled) text box so the screenshot stands in its place,
 *  exactly as the on-screen card hides the redundant snippet. */
const tableScreenshotReplacesText = (
  result: SearchResult,
  images: Map<string, FetchedImage>,
): boolean =>
  visualElementsFor(result).some((el) => {
    if (el.element_type !== 'table') return false;
    const path = visualElementPath(el);
    return !!path && images.has(path) && isTextRedundantWithTable(result.text, el);
  });

// ---------------------------------------------------------------------------
// Builders — one per section of the docx
// ---------------------------------------------------------------------------

const buildCoverParagraphs = (
  opts: ExportOptions,
  now: Date,
): Paragraph[] => {
  const children: Paragraph[] = [];
  children.push(
    new Paragraph({
      heading: HeadingLevel.TITLE,
      alignment: AlignmentType.LEFT,
      children: [
        new TextRun({ text: opts.documentTitle || 'Evidence Lab — Search Export', bold: true }),
      ],
    }),
  );
  // Demoted to H2 so the document has exactly two H1s — "AI Summary" and
  // "Search Results".
  children.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      children: [new TextRun({ text: opts.query || '(no query)', italics: true })],
      spacing: { after: 240 },
    }),
  );
  const meta: string[] = [];
  if (opts.dataSource) meta.push(`Dataset: ${opts.dataSource}`);
  meta.push(`Results: ${opts.results.length}`);
  meta.push(`Generated: ${now.toISOString().replace('T', ' ').slice(0, 16)} UTC`);
  children.push(
    new Paragraph({
      children: [new TextRun({ text: meta.join('  ·  '), size: 20, color: '555555' })],
      spacing: { after: opts.infoBox ? 120 : 360 },
    }),
  );
  if (opts.infoBox && opts.infoBox.trim()) {
    // A single bordered, lightly-shaded paragraph reads as a call-out box.
    const side = { style: BorderStyle.SINGLE, size: 6, color: 'E0C36A', space: 8 };
    children.push(
      new Paragraph({
        shading: { type: ShadingType.CLEAR, color: 'auto', fill: 'FBF4DD' },
        border: { top: side, bottom: side, left: side, right: side },
        spacing: { before: 60, after: 360, line: 276 },
        children: [
          new TextRun({ text: opts.infoBox.trim(), italics: true, size: 20, color: '6B5B2E' }),
        ],
      }),
    );
  }
  return children;
};

/** A clickable Table of Contents built from real content (not a Word field, so
 *  opening the document never prompts to "update fields"). Each entry is an
 *  internal hyperlink to a bookmark placed on the matching heading; the heading
 *  bookmarks are emitted by {@link markdownToParagraphs} in the same order. */
const buildManualToc = (summary: string, bookmarkPrefix: string): Paragraph[] => {
  const out: Paragraph[] = [
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: 'Contents' })],
      spacing: { after: 120 },
    }),
  ];
  extractMarkdownHeadings(summary).forEach((h, i) => {
    out.push(
      new Paragraph({
        spacing: { after: 60 },
        indent: h.depth > 1 ? { left: convertInchesToTwip(0.3 * (h.depth - 1)) } : undefined,
        children: [
          new InternalHyperlink({
            anchor: `${bookmarkPrefix}${i}`,
            children: [new TextRun({ text: h.text, style: 'Hyperlink' })],
          }),
        ],
      }),
    );
  });
  out.push(new Paragraph({ children: [new PageBreak()] }));
  return out;
};

const buildReferenceParagraphs = (
  groups: DocumentGroup[],
  ctx: CitationContext,
): Paragraph[] => {
  if (groups.length === 0) return [];
  const out: Paragraph[] = [];
  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      children: [new TextRun({ text: 'References' })],
      spacing: { before: 240, after: 120 },
    }),
  );
  // Each entry is a plain (non-bulleted) paragraph led by the document's
  // citation numbers in brackets, mirroring how citations appear inline:
  //   [1, 3] Doc title — Org, 2020, p.4, p.9
  // Each [N] is a clickable hyperlink to that specific result's page. The
  // title is unbolded so it reads as a reference line, not a heading.
  for (const group of groups) {
    const meta: string[] = [];
    if (group.organization) meta.push(group.organization);
    if (group.year) meta.push(group.year);
    const titleSuffix = meta.length ? ` — ${meta.join(', ')}` : '';

    const children: InlineChild[] = [];
    children.push(new TextRun({ text: '[' }));
    group.refs.forEach(({ sequential, result }, idx) => {
      if (idx > 0) children.push(new TextRun({ text: ', ' }));
      children.push(
        new ExternalHyperlink({
          link: resolveResultLink(result, ctx.siteOrigin, ctx.dataSource),
          children: [new TextRun({ text: String(sequential), style: 'Hyperlink' })],
        }),
      );
    });
    children.push(new TextRun({ text: '] ' }));
    children.push(new TextRun({ text: group.title + titleSuffix }));
    for (const { result } of group.refs) {
      if (typeof result.page_num === 'number') {
        children.push(new TextRun({ text: ', p.' + result.page_num, color: '555555' }));
      }
    }

    out.push(new Paragraph({ spacing: { after: 80 }, children }));
  }
  return out;
};

const buildSummarySection = (
  summary: string,
  results: SearchResult[],
  siteOrigin: string,
  dataSource?: string,
  heading = 'AI Summary',
  bookmarkPrefix?: string,
  footnotes?: FootnoteRegistry,
): Paragraph[] => {
  if (!summary.trim()) return [];
  const out: Paragraph[] = [];
  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: heading })],
      spacing: { before: 240, after: 120 },
    }),
  );
  const citations: CitationContext = {
    results,
    siteOrigin,
    dataSource,
    sequenceMap: buildCitationSequenceMap(summary, results),
    footnotes,
  };
  // Demote any markdown headings inside the summary by 1 so the section's
  // own H1 stays unique. Pass the citation context so [N] markers in the
  // body become clickable links, renumbered to match the screen. When a
  // bookmarkPrefix is set, headings are bookmarked for the manual TOC.
  out.push(...markdownToParagraphs(summary, 1, citations, bookmarkPrefix));
  out.push(...buildReferenceParagraphs(buildGroupedReferences(summary, results), citations));
  return out;
};

/** The FULL excerpt (never truncated) rendered as a single bordered, shaded box
 *  at a smaller font — one paragraph so the box stays continuous across page
 *  breaks, with blank lines separating sub-blocks. Returns nothing when there is
 *  no text, or when an embedded table screenshot already conveys it (the
 *  on-screen card hides the redundant snippet the same way). */
const buildExcerptParagraphs = (
  r: SearchResult,
  images: Map<string, FetchedImage>,
): Paragraph[] => {
  const blocks = normaliseExcerpt(String(r.text || ''))
    .split(/\n{2,}/)
    .map((b) => b.split('\n').join(' ').trim())
    .filter(Boolean);
  if (!blocks.length || tableScreenshotReplacesText(r, images)) return [];
  const excerptRuns: TextRun[] = [];
  blocks.forEach((b, i) => {
    if (i > 0) excerptRuns.push(new TextRun({ break: 2 }));
    excerptRuns.push(new TextRun({ text: b, italics: true, size: 18, color: '3A3A3A' }));
  });
  const boxSide = { style: BorderStyle.SINGLE, size: 4, color: 'D7DCE1', space: 8 };
  return [
    new Paragraph({
      shading: { type: ShadingType.CLEAR, color: 'auto', fill: 'F6F8FA' },
      border: { top: boxSide, bottom: boxSide, left: boxSide, right: boxSide },
      spacing: { after: 160, line: 252 },
      children: excerptRuns,
    }),
  ];
};

const buildResultCard = (
  r: SearchResult,
  idx: number,
  siteOrigin: string,
  dataSource: string | undefined,
  images: Map<string, FetchedImage>,
): Paragraph[] => {
  const out: Paragraph[] = [];
  const altTitle = typeof r.document_title === 'string' ? r.document_title : '';
  const title =
    (r.title && r.title.trim()) ||
    (altTitle && altTitle.trim()) ||
    '(untitled document)';
  const href = resolveResultLink(r, siteOrigin, dataSource);

  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_3,
      spacing: { before: 240, after: 80 },
      children: [
        new TextRun({ text: `${idx + 1}. `, bold: true }),
        new ExternalHyperlink({
          link: href,
          children: [new TextRun({ text: title, bold: true, style: 'Hyperlink' })],
        }),
      ],
    }),
  );

  const metaParts: string[] = [];
  if (r.organization) metaParts.push(String(r.organization));
  if (r.year) metaParts.push(String(r.year));
  if (typeof r.page_num === 'number') metaParts.push(`p. ${r.page_num}`);
  if (r.data_source || dataSource) metaParts.push(String(r.data_source || dataSource));
  if (typeof r.score === 'number') metaParts.push(`score ${r.score.toFixed(3)}`);
  out.push(
    new Paragraph({
      spacing: { after: 60 },
      children: [new TextRun({ text: metaParts.join('  ·  '), italics: true, size: 18, color: '555555' })],
    }),
  );

  const headings = Array.isArray(r.headings) ? r.headings.filter(Boolean) : [];
  if (headings.length) {
    out.push(
      new Paragraph({
        spacing: { after: 80 },
        children: [
          new TextRun({ text: 'Section: ', bold: true, size: 18 }),
          new TextRun({ text: headings.join(' › '), size: 18 }),
        ],
      }),
    );
  }

  // Embed the same table/figure screenshots shown on screen, in document order,
  // so a table renders as its image rather than mangled, flattened cell text,
  // followed by the FULL excerpt (unless a screenshot already conveys it).
  out.push(...buildResultImageParagraphs(r, images));
  out.push(...buildExcerptParagraphs(r, images));

  out.push(
    new Paragraph({
      spacing: { after: 240 },
      children: [
        new ExternalHyperlink({
          link: href,
          children: [new TextRun({ text: 'Open source document ›', style: 'Hyperlink', size: 18 })],
        }),
      ],
    }),
  );

  return out;
};

/**
 * A compact references list: one line per citation (flat) or per document
 * (grouped), title hyperlinked to the source, no excerpt text. Mirrors what
 * the Brief shows on screen so the export matches the reader's view.
 */
const buildReferenceList = (
  results: SearchResult[],
  siteOrigin: string,
  dataSource: string | undefined,
  grouped: boolean,
  sectionTitle = 'References',
): Paragraph[] => {
  const titleOf = (r: SearchResult): string =>
    (r.title && r.title.trim()) ||
    (typeof r.document_title === 'string' && r.document_title.trim()) ||
    '(untitled document)';

  const rows: Array<{ label: string; title: string; result: SearchResult }> = [];
  if (grouped) {
    const byDoc = new Map<string, { nums: number[]; result: SearchResult }>();
    results.forEach((r, idx) => {
      const key = r.doc_id || titleOf(r);
      const found = byDoc.get(key);
      if (found) found.nums.push(idx + 1);
      else byDoc.set(key, { nums: [idx + 1], result: r });
    });
    byDoc.forEach(({ nums, result }) =>
      rows.push({ label: nums.join(', '), title: titleOf(result), result }),
    );
  } else {
    results.forEach((r, idx) =>
      rows.push({
        label: String(idx + 1),
        title: `${titleOf(r)}${r.page_num ? `, p.${r.page_num}` : ''}`,
        result: r,
      }),
    );
  }

  const out: Paragraph[] = [
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: sectionTitle })],
      spacing: { before: 360, after: 120 },
    }),
  ];
  rows.forEach(({ label, title, result }) => {
    out.push(
      new Paragraph({
        spacing: { after: 60 },
        children: [
          new TextRun({ text: `${label}. `, bold: true }),
          new ExternalHyperlink({
            link: resolveResultLink(result, siteOrigin, dataSource),
            children: [new TextRun({ text: title, style: 'Hyperlink' })],
          }),
        ],
      }),
    );
  });
  return out;
};

const buildResultsSection = (
  results: SearchResult[],
  siteOrigin: string,
  dataSource: string | undefined,
  sectionTitle = 'Search Results',
  images: Map<string, FetchedImage> = new Map(),
): Paragraph[] => {
  const out: Paragraph[] = [];
  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: `${sectionTitle} (${results.length})` })],
      spacing: { before: 360, after: 120 },
    }),
  );
  results.forEach((r, idx) => {
    out.push(...buildResultCard(r, idx, siteOrigin, dataSource, images));
  });
  return out;
};

// ---------------------------------------------------------------------------
// Public entry points
// ---------------------------------------------------------------------------

/** Build the in-memory `docx` Document for the given export options. Exposed
 *  separately from {@link exportResultsToDocxBlob} to allow unit tests to
 *  introspect the document structure without packing a Blob. */
export const buildExportDocument = (
  opts: ExportOptions,
  images: Map<string, FetchedImage> = new Map(),
): Document => {
  const now = (opts.now ?? (() => new Date()))();
  const siteOrigin = opts.siteOrigin || 'https://evidencelab.ai';

  // In footnote mode, citations register footnotes as the prose renders; the
  // accumulated map is handed to the Document below.
  const footnotes =
    opts.citationStyle === 'footnotes' ? createFootnoteRegistry() : undefined;

  const tocBookmarkPrefix = 'briefheading';
  const body: Paragraph[] = [
    ...buildCoverParagraphs(opts, now),
    ...(opts.tableOfContents ? buildManualToc(opts.aiSummary ?? '', tocBookmarkPrefix) : []),
    ...buildSummarySection(
      opts.aiSummary ?? '',
      opts.results,
      siteOrigin,
      opts.dataSource,
      opts.summaryHeading,
      opts.tableOfContents ? tocBookmarkPrefix : undefined,
      footnotes,
    ),
    ...(opts.referenceList
      ? buildReferenceList(
          opts.results,
          siteOrigin,
          opts.dataSource,
          opts.referenceList === 'grouped',
          opts.resultsSectionTitle,
        )
      : buildResultsSection(
          opts.results,
          siteOrigin,
          opts.dataSource,
          opts.resultsSectionTitle,
          images,
        )),
  ];

  return new Document({
    creator: 'Evidence Lab',
    ...(footnotes && Object.keys(footnotes.map).length
      ? { footnotes: footnotes.map }
      : {}),
    title: opts.documentTitle ? opts.documentTitle : `Evidence Lab Search — ${opts.query}`,
    description: `Export of ${opts.results.length} search results` +
      (opts.aiSummary ? ' and the AI summary' : ''),
    // Match the web app's typography: Open Sans for body, Poppins for
    // headings. Sizes are in half-points — H1 is biggest and brand blue
    // (matches `--brand-primary` in App.css), H2 a step smaller and
    // greyish-dark, H3-H6 progressively smaller. Word falls back to
    // Calibri if Open Sans / Poppins aren't installed on the reader's
    // machine.
    styles: {
      default: {
        document: { run: { font: 'Open Sans' } },
        title: { run: { font: 'Poppins', bold: true, size: 48, color: '5B8FA8' } },
        heading1: { run: { font: 'Poppins', bold: true, size: 40, color: '5B8FA8' } },
        heading2: { run: { font: 'Poppins', bold: true, size: 28, color: '2C3E50' } },
        heading3: { run: { font: 'Poppins', bold: true, size: 24, color: '2C3E50' } },
        heading4: { run: { font: 'Poppins', bold: true, size: 22, color: '2C3E50' } },
        heading5: { run: { font: 'Poppins', bold: true, size: 22, color: '2C3E50' } },
        heading6: { run: { font: 'Poppins', bold: true, size: 22, color: '2C3E50' } },
      },
    },
    numbering: {
      config: [
        {
          reference: 'summary-ordered',
          levels: [
            {
              level: 0,
              format: LevelFormat.DECIMAL,
              text: '%1.',
              alignment: AlignmentType.START,
              style: { paragraph: { indent: { left: convertInchesToTwip(0.4), hanging: convertInchesToTwip(0.2) } } },
            },
          ],
        },
      ],
    },
    sections: [
      {
        properties: { page: { margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } } },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({
                    children: [
                      'Evidence Lab — page ',
                      PageNumber.CURRENT,
                      ' of ',
                      PageNumber.TOTAL_PAGES,
                    ],
                    size: 16,
                    color: '888888',
                  }),
                ],
              }),
            ],
          }),
        },
        children: body,
      },
    ],
  });
};

/** Serialise the export to a Word-compatible Blob. Table / figure screenshots
 *  are fetched first (when `fileBaseUrl` is set) so they can be embedded
 *  in-document; a screenshot that fails to fetch is skipped, never aborting the
 *  export. */
export const exportResultsToDocxBlob = async (opts: ExportOptions): Promise<Blob> => {
  const images = await fetchResultImages(opts);
  const doc = buildExportDocument(opts, images);
  const blob = await Packer.toBlob(doc);
  // docx's Packer returns a Blob with the generic zip MIME — override so
  // consumers (and tests) see the Word-specific type.
  return new Blob([blob], { type: DOCX_MIME });
};
