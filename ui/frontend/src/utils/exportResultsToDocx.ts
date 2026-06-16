/**
 * Client-side generator for a nicely-formatted Word (.docx) export of a
 * search result set, including the AI summary.
 *
 * The export is produced entirely in the browser using the `docx` package —
 * no backend round-trip is required. The resulting Blob can be handed to
 * `file-saver`'s `saveAs` for download.
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
  Document,
  ExternalHyperlink,
  Footer,
  HeadingLevel,
  LevelFormat,
  Packer,
  PageNumber,
  Paragraph,
  TextRun,
  convertInchesToTwip,
} from 'docx';
import type { SearchResult } from '../types/api';
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

/** Inline children of a Paragraph: either plain runs or hyperlink containers.
 *  `Paragraph.children` accepts both, so we expose this union. */
type InlineChild = TextRun | ExternalHyperlink;

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
): Paragraph | null => {
  const h = /^(#{1,6})\s+(.*)$/.exec(line);
  if (h) {
    const depth = Math.min(6, Math.max(1, h[1].length + headingShift));
    const heading = HEADING_LEVELS_BY_DEPTH[depth] ?? HeadingLevel.HEADING_6;
    // Headings stay text-only — rendering hyperlinks inside a heading
    // confuses Word's outline view, so omit the citation context here.
    return new Paragraph({
      heading,
      children: inlineRuns(h[2]),
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

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line === '') {
      flushParagraph();
      continue;
    }
    const block = matchBlockParagraph(line, headingShift, citations);
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
      children: [new TextRun({ text: 'Evidence Lab — Search Export', bold: true })],
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
      spacing: { after: 360 },
    }),
  );
  return children;
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
  //   [1, 3]  Doc title — Org, 2020   p.4   p.9
  // Each [N] is a clickable hyperlink to that specific result's page.
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
    children.push(new TextRun({ text: group.title + titleSuffix, bold: true }));
    for (const { result } of group.refs) {
      if (typeof result.page_num === 'number') {
        children.push(new TextRun({ text: '   p.' + result.page_num, color: '555555' }));
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
): Paragraph[] => {
  if (!summary.trim()) return [];
  const out: Paragraph[] = [];
  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: 'AI Summary' })],
      spacing: { before: 240, after: 120 },
    }),
  );
  const citations: CitationContext = {
    results,
    siteOrigin,
    dataSource,
    sequenceMap: buildCitationSequenceMap(summary),
  };
  // Demote any markdown headings inside the summary by 1 so the section's
  // own H1 stays unique. Pass the citation context so [N] markers in the
  // body become clickable links, renumbered to match the screen.
  out.push(...markdownToParagraphs(summary, 1, citations));
  out.push(...buildReferenceParagraphs(buildGroupedReferences(summary, results), citations));
  return out;
};

const buildResultCard = (
  r: SearchResult,
  idx: number,
  siteOrigin: string,
  dataSource?: string,
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

  const excerpt = normaliseExcerpt(String(r.text || ''));
  const blocks = excerpt.split(/\n{2,}/);
  for (const block of blocks) {
    const inner = block.split('\n').join(' ').trim();
    if (!inner) continue;
    out.push(
      new Paragraph({
        spacing: { after: 120 },
        children: [new TextRun({ text: inner })],
      }),
    );
  }

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

const buildResultsSection = (
  results: SearchResult[],
  siteOrigin: string,
  dataSource?: string,
): Paragraph[] => {
  const out: Paragraph[] = [];
  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: `Search Results (${results.length})` })],
      spacing: { before: 360, after: 120 },
    }),
  );
  results.forEach((r, idx) => {
    out.push(...buildResultCard(r, idx, siteOrigin, dataSource));
  });
  return out;
};

// ---------------------------------------------------------------------------
// Public entry points
// ---------------------------------------------------------------------------

/** Build the in-memory `docx` Document for the given export options. Exposed
 *  separately from {@link exportResultsToDocxBlob} to allow unit tests to
 *  introspect the document structure without packing a Blob. */
export const buildExportDocument = (opts: ExportOptions): Document => {
  const now = (opts.now ?? (() => new Date()))();
  const siteOrigin = opts.siteOrigin || 'https://evidencelab.ai';

  const body: Paragraph[] = [
    ...buildCoverParagraphs(opts, now),
    ...buildSummarySection(opts.aiSummary ?? '', opts.results, siteOrigin, opts.dataSource),
    ...buildResultsSection(opts.results, siteOrigin, opts.dataSource),
  ];

  return new Document({
    creator: 'Evidence Lab',
    title: `Evidence Lab Search — ${opts.query}`,
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

/** Serialise the export to a Word-compatible Blob. */
export const exportResultsToDocxBlob = async (opts: ExportOptions): Promise<Blob> => {
  const doc = buildExportDocument(opts);
  const blob = await Packer.toBlob(doc);
  // docx's Packer returns a Blob with the generic zip MIME — override so
  // consumers (and tests) see the Word-specific type.
  return new Blob([blob], { type: DOCX_MIME });
};
