import { DrilldownNode, SearchResult } from '../types/api';
import { buildGroupedReferences, DocumentGroup } from '../components/AiSummaryReferences';

/** Escape HTML special characters */
const esc = (text: string): string =>
  text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

/** Convert a label to a URL-safe anchor id */
const toAnchorId = (label: string, index: number): string =>
  `section-${index}-${label.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase()}`;

/** Resolve a SearchResult to its external source document URL */
const resolveSourceUrl = (result: SearchResult): string =>
  result.report_url ||
  result.metadata?.report_url ||
  result.metadata?.map_report_url ||
  result.metadata?.src_doc_raw_metadata?.report_url ||
  result.pdf_url ||
  result.metadata?.pdf_url ||
  result.metadata?.map_pdf_url ||
  result.metadata?.src_doc_raw_metadata?.pdf_url ||
  '';

/** Build a map from original citation number to { url, sequential } */
const buildCitationLinks = (
  summary: string,
  results: SearchResult[]
): Map<number, { url: string; seq: number }> => {
  const cited = new Set<number>();
  const regex = /\[(\d+(?:,\s*\d+)*)\]/g;
  let match;
  while ((match = regex.exec(summary)) !== null) {
    match[1].split(',').forEach((n) => {
      const num = parseInt(n.trim(), 10);
      if (num >= 1 && num <= results.length) cited.add(num);
    });
  }
  const sorted = Array.from(cited).sort((a, b) => a - b);
  const map = new Map<number, { url: string; seq: number }>();
  sorted.forEach((origNum, idx) => {
    const r = results[origNum - 1];
    let url = resolveSourceUrl(r);
    if (url && r.page_num) url += `#page=${r.page_num}`;
    map.set(origNum, { url, seq: idx + 1 });
  });
  return map;
};

/** Parse inline markdown (bold, italic, citations) to HTML */
const parseInlineMarkdown = (
  line: string,
  linkMap?: Map<number, { url: string; seq: number }>
): string =>
  esc(line)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(
      /\[(\d+(?:,\s*\d+)*)\]/g,
      (_, nums: string) => {
        if (!linkMap) {
          return `<sup class="citation">[${nums}]</sup>`;
        }
        const parts = nums.split(/,\s*/).map((n) => {
          const orig = parseInt(n, 10);
          const entry = linkMap.get(orig);
          if (!entry) return n;
          if (entry.url) {
            return `<a href="${entry.url}" target="_blank" class="citation-link">${entry.seq}</a>`;
          }
          return `${entry.seq}`;
        });
        return `<sup class="citation">[${parts.join(', ')}]</sup>`;
      }
    );

/** Wrap consecutive <li> elements in <ul> tags */
const wrapListItems = (htmlLines: string[]): string => {
  const result: string[] = [];
  let inList = false;

  for (const line of htmlLines) {
    if (line.startsWith('<li>')) {
      if (!inList) {
        result.push('<ul>');
        inList = true;
      }
      result.push(line);
    } else {
      if (inList) {
        result.push('</ul>');
        inList = false;
      }
      result.push(line);
    }
  }
  if (inList) result.push('</ul>');

  return result.join('\n');
};

/** Parse a single line of markdown into an HTML string */
const parseMarkdownLine = (
  trimmed: string,
  linkMap?: Map<number, { url: string; seq: number }>
): string | null => {
  if (!trimmed) return null;

  const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
  if (headingMatch) {
    const level = Math.min(headingMatch[1].length + 2, 6);
    return `<h${level}>${parseInlineMarkdown(headingMatch[2], linkMap)}</h${level}>`;
  }

  const boldHeadingMatch = trimmed.match(/^\*\*(.+?)\*\*:?\s*$/);
  if (boldHeadingMatch) {
    return `<p><strong>${esc(boldHeadingMatch[1])}</strong></p>`;
  }

  if (/^[-*]\s/.test(trimmed)) {
    return `<li>${parseInlineMarkdown(trimmed.replace(/^[-*]\s/, ''), linkMap)}</li>`;
  }

  if (/^\d+[.)]\s/.test(trimmed)) {
    return `<li>${parseInlineMarkdown(trimmed.replace(/^\d+[.)]\s/, ''), linkMap)}</li>`;
  }

  return `<p>${parseInlineMarkdown(trimmed, linkMap)}</p>`;
};

/** Parse a full markdown summary into HTML paragraphs */
const parseSummaryToHtml = (
  summary: string,
  results?: SearchResult[]
): string => {
  const linkMap = results
    ? buildCitationLinks(summary, results)
    : undefined;

  const blocks = summary.split(/\n\n+/);
  const parts: string[] = [];

  for (const block of blocks) {
    const lines = block.split('\n');
    const htmlLines: string[] = [];
    for (const line of lines) {
      const parsed = parseMarkdownLine(line.trim(), linkMap);
      if (parsed) htmlLines.push(parsed);
    }
    parts.push(wrapListItems(htmlLines));
  }

  return parts.join('\n');
};

/** Build HTML for a references section */
const buildReferencesHtml = (groups: DocumentGroup[]): string => {
  if (groups.length === 0) return '';

  const items = groups.map((group) => {
    const meta = [group.title, group.organization, group.year]
      .filter(Boolean)
      .join(', ');
    const citations = group.refs
      .map(({ sequential, result }) => {
        const page = result.page_num ? ` p.${result.page_num}` : '';
        let url = resolveSourceUrl(result);
        if (url && result.page_num) url += `#page=${result.page_num}`;
        if (url) {
          return `<a href="${url}" target="_blank" class="citation-link">[${sequential}]${page}</a>`;
        }
        return `<span>[${sequential}]${page}</span>`;
      })
      .join(' ');
    return `<li class="ref-item">${esc(meta)} | ${citations}</li>`;
  });

  return `<div class="references"><h4>References</h4><ul>${items.join('\n')}</ul></div>`;
};

interface TocEntry {
  id: string;
  label: string;
  depth: number;
}

/** Build a visual tree graph from the drilldown nodes */
const buildNodeGraphHtml = (
  node: DrilldownNode,
  isRoot: boolean
): string => {
  const label = `<span class="graph-label">${esc(node.label)}</span>`;
  if (node.children.length === 0) {
    return isRoot
      ? `<div class="tree-graph"><ul><li>${label}</li></ul></div>`
      : `<li>${label}</li>`;
  }
  const kids = node.children.map((c) => buildNodeGraphHtml(c, false)).join('\n');
  const inner = `${label}<ul>${kids}</ul>`;
  return isRoot
    ? `<div class="tree-graph"><ul><li>${inner}</li></ul></div>`
    : `<li>${inner}</li>`;
};

const buildGraphHtml = (
  tree: DrilldownNode,
  hasGlobal: boolean
): string => {
  if (!hasGlobal) return buildNodeGraphHtml(tree, true);
  const globalLabel = '<span class="graph-label">Global Summary</span>';
  const treeHtml = buildNodeGraphHtml(tree, false);
  return `<div class="tree-graph"><ul><li>${globalLabel}<ul>${treeHtml}</ul></li></ul></div>`;
};

/** Collect TOC entries and section HTML from the tree recursively */
const buildTreeSections = (
  node: DrilldownNode,
  depth: number,
  toc: TocEntry[],
  counter: { value: number }
): string => {
  let html = '';

  if (node.summary) {
    const idx = counter.value++;
    const id = toAnchorId(node.label, idx);
    const hLevel = Math.min(depth + 2, 6);
    toc.push({ id, label: node.label, depth });

    const heading = `<h${hLevel} id="${id}">${esc(node.label)}</h${hLevel}>`;
    const content = parseSummaryToHtml(node.summary, node.results);
    const refs = buildReferencesHtml(
      buildGroupedReferences(node.summary, node.results)
    );

    html += `${heading}\n${content}\n${refs}\n`;
  }

  for (const child of node.children) {
    html += buildTreeSections(child, depth + 1, toc, counter);
  }

  return html;
};

/** Build the TOC HTML from collected entries */
const buildTocHtml = (entries: TocEntry[]): string => {
  const items = entries.map((entry) => {
    const indent = entry.depth * 20;
    return `<li style="margin-left:${indent}px"><a href="#${entry.id}">${esc(entry.label)}</a></li>`;
  });
  return `<nav class="toc"><h2>Table of Contents</h2><ul>${items.join('\n')}</ul></nav>`;
};

const PRINT_CSS = `
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 0 auto; padding: 40px 30px; color: #1a1a1a; line-height: 1.6; }
  h1 { font-size: 1.6rem; border-bottom: 2px solid #5B8FA8; padding-bottom: 6px; margin-top: 0; }
  .report-header { display: flex; align-items: center; gap: 12px; border-bottom: 2px solid #5B8FA8; padding-bottom: 8px; margin-bottom: 24px; }
  .report-header img { height: 36px; width: auto; }
  .report-header h1 { border-bottom: none; padding-bottom: 0; margin-bottom: 0; }
  h2 { font-size: 1.3rem; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 28px; }
  h3 { font-size: 1.1rem; margin-top: 20px; }
  h4 { font-size: 1rem; margin-top: 14px; color: #444; }
  h5, h6 { font-size: 0.95rem; margin-top: 10px; }
  p { margin: 6px 0; font-size: 0.95rem; }
  ul { padding-left: 20px; }
  li { margin: 3px 0; font-size: 0.95rem; }
  .citation { color: #5B8FA8; font-size: 0.7em; }
  .citation-link { color: #5B8FA8; text-decoration: none; }
  .citation-link:hover { text-decoration: underline; }
  .references { background: #f8f9fa; border-left: 3px solid #5B8FA8; padding: 10px 14px; margin: 14px 0; }
  .references h4 { margin-top: 0; color: #5B8FA8; }
  .references ul { list-style: none; padding-left: 0; }
  .ref-item { font-size: 0.85rem; margin: 4px 0; color: #555; }
  .tree-graph { margin: 16px 0 28px; }
  .tree-graph ul { list-style: none; padding-left: 24px; position: relative; }
  .tree-graph > ul { padding-left: 0; }
  .tree-graph li { position: relative; padding: 4px 0 4px 16px; }
  .tree-graph li::before { content: ''; position: absolute; left: -8px; top: 14px; width: 16px; border-top: 2px solid #5B8FA8; }
  .tree-graph li::after { content: ''; position: absolute; left: -8px; top: 0; bottom: 0; border-left: 2px solid #5B8FA8; }
  .tree-graph li:last-child::after { bottom: calc(100% - 14px); }
  .tree-graph > ul > li::before, .tree-graph > ul > li::after { display: none; }
  .graph-label { display: inline-block; padding: 3px 10px; border: 1px solid #5B8FA8; border-radius: 4px; background: #f8f9fa; font-size: 0.85rem; color: #1a1a1a; }
  .toc { margin-bottom: 28px; }
  .toc ul { list-style: none; padding-left: 0; }
  .toc li { margin: 3px 0; font-size: 0.95rem; }
  .toc a { color: #5B8FA8; text-decoration: none; }
  .toc a:hover { text-decoration: underline; }
  @media print {
    body { padding: 20px; max-width: none; }
    .toc a { color: #333; }
    .references { break-inside: avoid; }
    h2, h3, h4 { break-after: avoid; }
  }
`;

/** Export the drilldown tree as a print-ready PDF document */
export const exportResearchToPdf = (
  tree: DrilldownNode,
  globalSummary?: string,
  globalSummaryResults?: SearchResult[]
): void => {
  const toc: TocEntry[] = [];
  const counter = { value: 0 };
  let bodyHtml = '';

  // Global summary section
  if (globalSummary) {
    const globalResults = globalSummaryResults || [];
    const globalId = toAnchorId('Global Summary', counter.value++);
    toc.push({ id: globalId, label: 'Global Summary', depth: 0 });
    bodyHtml += `<h1 id="${globalId}">Global Summary</h1>\n`;
    bodyHtml += parseSummaryToHtml(globalSummary, globalResults);
    bodyHtml += buildReferencesHtml(
      buildGroupedReferences(globalSummary, globalResults)
    );
  }

  // Tree sections
  bodyHtml += buildTreeSections(tree, 0, toc, counter);

  const tocHtml = buildTocHtml(toc);
  const graphHtml = buildGraphHtml(tree, !!globalSummary);
  const docTitle = 'Evidence Lab - AI Summary Tree';
  const querySlug = tree.label
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .toLowerCase()
    .slice(0, 60);
  const fileTitle = `${docTitle} - ${querySlug}`;

  const fullHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>${esc(fileTitle)}</title>
<style>${PRINT_CSS}</style>
</head>
<body>
<div class="report-header">
<img src="/logo.png" alt="Evidence Lab" />
<h1>${docTitle}</h1>
</div>
${graphHtml}
${tocHtml}
${bodyHtml}
<script>window.onload = function() { window.print(); }<\/script>
</body>
</html>`;

  const printWindow = window.open('', '_blank');
  if (printWindow) {
    printWindow.document.write(fullHtml);
    printWindow.document.close();
  }
};
