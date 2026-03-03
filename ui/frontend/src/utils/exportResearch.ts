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

/** Parse inline markdown (bold, italic, citations) to HTML */
const parseInlineMarkdown = (line: string): string =>
  esc(line)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(
      /\[(\d+(?:,\s*\d+)*)\]/g,
      '<sup class="citation">[$1]</sup>'
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
const parseMarkdownLine = (trimmed: string): string | null => {
  if (!trimmed) return null;

  const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
  if (headingMatch) {
    const level = Math.min(headingMatch[1].length + 2, 6);
    return `<h${level}>${parseInlineMarkdown(headingMatch[2])}</h${level}>`;
  }

  const boldHeadingMatch = trimmed.match(/^\*\*(.+?)\*\*:?\s*$/);
  if (boldHeadingMatch) {
    return `<p><strong>${esc(boldHeadingMatch[1])}</strong></p>`;
  }

  if (/^[-*]\s/.test(trimmed)) {
    return `<li>${parseInlineMarkdown(trimmed.replace(/^[-*]\s/, ''))}</li>`;
  }

  if (/^\d+[.)]\s/.test(trimmed)) {
    return `<li>${parseInlineMarkdown(trimmed.replace(/^\d+[.)]\s/, ''))}</li>`;
  }

  return `<p>${parseInlineMarkdown(trimmed)}</p>`;
};

/** Parse a full markdown summary into HTML paragraphs */
const parseSummaryToHtml = (summary: string): string => {
  const blocks = summary.split(/\n\n+/);
  const parts: string[] = [];

  for (const block of blocks) {
    const lines = block.split('\n');
    const htmlLines: string[] = [];
    for (const line of lines) {
      const parsed = parseMarkdownLine(line.trim());
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
        return `[${sequential}]${page}`;
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

/** Collect TOC entries and section HTML from the tree recursively */
const buildTreeSections = (
  node: DrilldownNode,
  depth: number,
  toc: TocEntry[],
  counter: { value: number }
): string => {
  if (!node.summary) return '';

  const idx = counter.value++;
  const id = toAnchorId(node.label, idx);
  const hLevel = Math.min(depth + 2, 6);
  toc.push({ id, label: node.label, depth });

  const heading = `<h${hLevel} id="${id}">${esc(node.label)}</h${hLevel}>`;
  const content = parseSummaryToHtml(node.summary);
  const refs = buildReferencesHtml(
    buildGroupedReferences(node.summary, node.results)
  );

  let html = `${heading}\n${content}\n${refs}\n`;

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
  h2 { font-size: 1.3rem; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 28px; }
  h3 { font-size: 1.1rem; margin-top: 20px; }
  h4 { font-size: 1rem; margin-top: 14px; color: #444; }
  h5, h6 { font-size: 0.95rem; margin-top: 10px; }
  p { margin: 6px 0; font-size: 0.95rem; }
  ul { padding-left: 20px; }
  li { margin: 3px 0; font-size: 0.95rem; }
  .citation { color: #5B8FA8; font-size: 0.7em; }
  .references { background: #f8f9fa; border-left: 3px solid #5B8FA8; padding: 10px 14px; margin: 14px 0; }
  .references h4 { margin-top: 0; color: #5B8FA8; }
  .references ul { list-style: none; padding-left: 0; }
  .ref-item { font-size: 0.85rem; margin: 4px 0; color: #555; }
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
    const globalId = toAnchorId('Global Summary', counter.value++);
    toc.push({ id: globalId, label: 'Global Summary', depth: 0 });
    bodyHtml += `<h1 id="${globalId}">Global Summary</h1>\n`;
    bodyHtml += parseSummaryToHtml(globalSummary);
    bodyHtml += buildReferencesHtml(
      buildGroupedReferences(globalSummary, globalSummaryResults || [])
    );
  }

  // Tree sections
  bodyHtml += buildTreeSections(tree, 0, toc, counter);

  const tocHtml = buildTocHtml(toc);
  const title = tree.label || 'Research Export';

  const fullHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Evidence Lab - AI Summary Tree - ${esc(title)}</title>
<style>${PRINT_CSS}</style>
</head>
<body>
<h1>Evidence Lab - AI Summary Tree</h1>
<h2>${esc(title)}</h2>
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
