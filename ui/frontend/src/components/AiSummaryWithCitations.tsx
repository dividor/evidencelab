import React from 'react';
import { SearchResult } from '../types/api';
import { renderMarkdownText } from '../utils/textHighlighting';

interface AiSummaryWithCitationsProps {
  summaryText: string;
  searchResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
  onFindOutMore?: (keyFacts: string[]) => void;
  findOutMoreLoading?: boolean;
  findOutMoreActiveFact?: string | null;
}

const CITATION_REGEX = /\[(\d+(?:,\s*\d+)*)\]/g;
const CITATION_ONLY_LINE = /^\[[\d,\s]+\]$/;
const NUMBERED_LIST_REGEX = /^\d+[\.)]\s/;
const BULLET_LIST_REGEX = /^[-*]\s/;
const HEADING_REGEX = /^(#{1,4})\s+(.+)$/;
const BOLD_HEADING_REGEX = /^\*\*(.+?)\*\*:?\s*$/;
const PLAIN_HEADING_REGEX = /^([A-Z][A-Za-z\s]+):?\s*$/;

const parseCitationNumbers = (rawNumbers: string): number[] =>
  rawNumbers.split(',').map((item) => parseInt(item.trim(), 10));

const extractKeyFacts = (summary: string): string[] => {
  const lines = summary.split('\n');
  let inKeyFacts = false;
  const items: Array<{ fact: string; citations: number }> = [];
  for (const line of lines) {
    const trimmed = line.trim();
    const heading = parseHeading(trimmed);
    if (heading) {
      if (/key\s*facts/i.test(heading.text)) { inKeyFacts = true; continue; }
      if (inKeyFacts) break;
    }
    if (inKeyFacts && BULLET_LIST_REGEX.test(trimmed)) {
      const fact = trimmed.replace(BULLET_LIST_REGEX, '').replace(CITATION_REGEX, '').trim();
      if (fact) items.push({ fact, citations: countCitations(trimmed) });
    }
  }
  // Sort by citation count descending to match displayed order
  items.sort((a, b) => b.citations - a.citations);
  return items.map((i) => i.fact);
};

const extractSubHeadings = (summary: string): string[] => {
  const lines = summary.split('\n');
  let firstLevel: number | null = null;
  const subHeadings: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    const heading = parseHeading(trimmed);
    if (!heading) continue;
    if (/key\s*facts/i.test(heading.text)) continue;
    if (firstLevel === null) {
      firstLevel = heading.level;
      continue;
    }
    // Collect headings at a deeper level than the first
    if (heading.level >= firstLevel) {
      const text = heading.text.replace(CITATION_REGEX, '').trim();
      if (text) subHeadings.push(text);
    }
  }
  return subHeadings;
};

const buildCitationMapping = (summaryText: string): Map<number, number> => {
  const citedNumbers = new Set<number>();
  let match;

  while ((match = CITATION_REGEX.exec(summaryText)) !== null) {
    const numbers = parseCitationNumbers(match[1]);
    numbers.forEach((num) => citedNumbers.add(num));
  }

  const citationMapping = new Map<number, number>();
  const sortedCitations = Array.from(citedNumbers).sort((a, b) => a - b);
  sortedCitations.forEach((origNum, seqIdx) => {
    citationMapping.set(origNum, seqIdx + 1);
  });
  return citationMapping;
};

const splitSummaryBlocks = (summaryText: string): string[] =>
  summaryText.split(/\n\n+/);

const parseHeading = (trimmed: string): { text: string; level: number } | null => {
  const mdMatch = trimmed.match(HEADING_REGEX);
  if (mdMatch) return { text: mdMatch[2], level: Math.min(mdMatch[1].length + 2, 6) };
  const boldMatch = trimmed.match(BOLD_HEADING_REGEX);
  if (boldMatch) return { text: boldMatch[1], level: 4 };
  const plainMatch = trimmed.match(PLAIN_HEADING_REGEX);
  if (plainMatch) return { text: plainMatch[1], level: 4 };
  return null;
};


const stripListPrefix = (line: string, listType: 'numbered' | 'bullet'): string => {
  if (listType === 'numbered') {
    return line.replace(NUMBERED_LIST_REGEX, '');
  }
  return line.trim().replace(/^[-*]\s/, '');
};

const countCitations = (text: string): number => {
  let count = 0;
  const re = new RegExp(CITATION_REGEX.source, 'g');
  let m;
  while ((m = re.exec(text)) !== null) {
    count += parseCitationNumbers(m[1]).length;
  }
  return count;
};

const buildCitationLinkTitle = (result: SearchResult): string => {
  const yearSuffix = result.year ? ', ' + result.year : '';
  return result.title + ' (' + (result.organization || 'Unknown') + yearSuffix + ')';
};

interface CitationEntry {
  sequentialNumber: number;
  result: SearchResult | null;
  idx: number;
}

const buildCitationEntries = (
  rawNumbers: string,
  searchResults: SearchResult[],
  citationMapping: Map<number, number>,
): CitationEntry[] => {
  const entries: CitationEntry[] = [];
  for (const originalNumber of parseCitationNumbers(rawNumbers)) {
    const sequentialNumber = citationMapping.get(originalNumber);
    if (sequentialNumber === undefined) continue;
    const citationIndex = originalNumber - 1;
    const result = citationIndex >= 0 && citationIndex < searchResults.length
      ? searchResults[citationIndex] : null;
    entries.push({ sequentialNumber, result, idx: entries.length });
  }
  return entries;
};

const groupByDocument = (entries: CitationEntry[]): CitationEntry[][] => {
  const groups: CitationEntry[][] = [];
  for (const entry of entries) {
    const docId = entry.result?.doc_id;
    const prev = groups.length > 0 ? groups[groups.length - 1] : null;
    const prevDocId = prev && prev[0].result?.doc_id;
    if (prev && docId && docId === prevDocId) {
      prev.push(entry);
    } else {
      groups.push([entry]);
    }
  }
  return groups;
};

const renderCitationLink = (
  entry: CitationEntry,
  onResultClick: (result: SearchResult) => void,
  keyPrefix: string,
): React.ReactNode => {
  if (entry.result) {
    return (
      <a
        key={`${keyPrefix}-link-${entry.sequentialNumber}-${entry.idx}`}
        href="#"
        className="ai-summary-citation"
        onClick={(event: React.MouseEvent) => {
          event.preventDefault();
          onResultClick(entry.result!);
        }}
        title={buildCitationLinkTitle(entry.result)}
      >
        {entry.sequentialNumber}
      </a>
    );
  }
  return (
    <span key={`${keyPrefix}-missing-${entry.sequentialNumber}-${entry.idx}`}>
      {entry.sequentialNumber}
    </span>
  );
};

const renderCitationLinks = (
  rawNumbers: string,
  searchResults: SearchResult[],
  citationMapping: Map<number, number>,
  onResultClick: (result: SearchResult) => void,
  keyPrefix: string
): React.ReactNode[] => {
  const entries = buildCitationEntries(rawNumbers, searchResults, citationMapping);
  const groups = groupByDocument(entries);
  const nodes: React.ReactNode[] = [];

  groups.forEach((group, gi) => {
    if (gi > 0) nodes.push(<span key={`${keyPrefix}-gsep-${gi}`}> </span>);
    const inner = group.map((entry, ei) => (
      <React.Fragment key={`${keyPrefix}-e-${entry.idx}`}>
        {ei > 0 && <span>, </span>}
        {renderCitationLink(entry, onResultClick, keyPrefix)}
      </React.Fragment>
    ));
    nodes.push(
      <span key={`${keyPrefix}-dg-${gi}`} className="citation-doc-group">
        {inner}
      </span>
    );
  });

  return nodes;
};

const renderLineWithCitations = (
  text: string,
  searchResults: SearchResult[],
  citationMapping: Map<number, number>,
  onResultClick: (result: SearchResult) => void,
  keyPrefix: string
): React.ReactNode => {
  const segments = text.split(CITATION_REGEX);
  if (segments.length === 1) {
    return renderMarkdownText(text);
  }

  const parts = segments.map((segment, idx) => {
    if (idx % 2 === 1) {
      const citationLinks = renderCitationLinks(
        segment,
        searchResults,
        citationMapping,
        onResultClick,
        `${keyPrefix}-${idx}`
      );
      return (
        <span key={`${keyPrefix}-group-${idx}`}>
          {citationLinks}
        </span>
      );
    }
    return <React.Fragment key={`${keyPrefix}-text-${idx}`}>{renderMarkdownText(segment)}</React.Fragment>;
  });

  return <>{parts}</>;
};

const renderHeadingElement = (
  heading: { text: string; level: number },
  key: string,
  content: React.ReactNode,
  opts: {
    isKeyFacts: boolean;
    isFirstHeading: boolean;
    summaryText: string;
    onFindOutMore?: (items: string[]) => void;
    findOutMoreLoading?: boolean;
    findOutMoreActiveFact?: string | null;
  },
): React.ReactNode => {
  const { level } = heading;
  const { isKeyFacts, isFirstHeading, summaryText: text, onFindOutMore, findOutMoreLoading, findOutMoreActiveFact } = opts;
  const headingText = heading.text.replace(CITATION_REGEX, '').trim();
  const isActiveHeading = !isKeyFacts && findOutMoreActiveFact && headingText === findOutMoreActiveFact;
  const btnLabel = findOutMoreLoading ? 'Researching...' : 'Find out more';
  const btnTooltip = 'Click this to have the system automatically drill-down into the topics mentioned below. You can save your research to your profile to pick up where you left off.';

  if (isKeyFacts && onFindOutMore) {
    return (
      <div key={key} className="ai-key-facts-header">
        {React.createElement(`h${level}`, null, content)}
        <button className="ai-find-out-more-btn" disabled={findOutMoreLoading} data-tooltip={btnTooltip}
          onClick={(e) => { e.preventDefault(); onFindOutMore(extractKeyFacts(text)); }}>
          {btnLabel}
        </button>
      </div>
    );
  }
  if (isFirstHeading && onFindOutMore && !isKeyFacts) {
    const subHeadings = extractSubHeadings(text);
    return (
      <div key={key} className="ai-key-facts-header">
        {React.createElement(`h${level}`, null, content)}
        {subHeadings.length > 0 && (
          <button className="ai-find-out-more-btn" disabled={findOutMoreLoading} data-tooltip={btnTooltip}
            onClick={(e) => { e.preventDefault(); onFindOutMore(subHeadings); }}>
            {btnLabel}
          </button>
        )}
      </div>
    );
  }
  if (isActiveHeading) {
    return (
      <div key={key} className="ai-heading-active">
        {React.createElement(`h${level}`, null, content)}
      </div>
    );
  }
  return React.createElement(`h${level}`, { key }, content);
};

export const AiSummaryWithCitations: React.FC<AiSummaryWithCitationsProps> = ({
  summaryText,
  searchResults,
  onResultClick,
  onFindOutMore,
  findOutMoreLoading,
  findOutMoreActiveFact,
}) => {
  const citationMapping = buildCitationMapping(summaryText);
  const blocks = splitSummaryBlocks(summaryText);
  // Track across all blocks so only the very first heading gets the button
  let isFirstHeadingGlobal = true;

  return (
    <>
      {blocks.map((block, blockIndex) => {
        if (!block.trim()) return null;
        const lines = block.split(/\n/);

        const elements: React.ReactNode[] = [];
        let pendingParagraphLines: string[] = [];
        let pendingListItems: string[] = [];
        let pendingListType: 'numbered' | 'bullet' | null = null;
        let afterKeyFacts = false;

        const flushParagraph = () => {
          if (pendingParagraphLines.length === 0) return;
          elements.push(
            <p key={`${blockIndex}-p-${elements.length}`}>
              {pendingParagraphLines.map((line, li) => (
                <React.Fragment key={li}>
                  {li > 0 && <br />}
                  {renderLineWithCitations(line, searchResults, citationMapping, onResultClick, `${blockIndex}-${elements.length}-${li}`)}
                </React.Fragment>
              ))}
            </p>
          );
          pendingParagraphLines = [];
        };

        const flushList = () => {
          if (pendingListItems.length === 0 || !pendingListType) return;
          const ListTag: React.ElementType = pendingListType === 'numbered' ? 'ol' : 'ul';
          const lt = pendingListType;
          const items = afterKeyFacts
            ? [...pendingListItems].sort((a, b) => countCitations(b) - countCitations(a))
            : pendingListItems;
          elements.push(
            <ListTag key={`${blockIndex}-list-${elements.length}`}>
              {items.map((item, li) => {
                const stripped = stripListPrefix(item, lt);
                const isActive = afterKeyFacts && findOutMoreActiveFact &&
                  stripped.replace(CITATION_REGEX, '').trim() === findOutMoreActiveFact;
                return (
                  <li key={li} className={isActive ? 'ai-fact-active' : ''}>
                    {renderLineWithCitations(stripped, searchResults, citationMapping, onResultClick, `${blockIndex}-${elements.length}-${li}`)}
                  </li>
                );
              })}
            </ListTag>
          );
          pendingListItems = [];
          pendingListType = null;
          afterKeyFacts = false;
        };

        lines.forEach((line) => {
          const trimmed = line.trim();
          if (!trimmed || CITATION_ONLY_LINE.test(trimmed)) return;

          const heading = parseHeading(trimmed);
          if (heading) {
            flushParagraph();
            flushList();
            const isKeyFacts = /key\s*facts/i.test(heading.text);
            afterKeyFacts = isKeyFacts;
            const content = renderLineWithCitations(heading.text, searchResults, citationMapping, onResultClick, `${blockIndex}-h-${elements.length}`);
            elements.push(renderHeadingElement(heading, `${blockIndex}-h-${elements.length}`, content, {
              isKeyFacts, isFirstHeading: isFirstHeadingGlobal, summaryText, onFindOutMore, findOutMoreLoading, findOutMoreActiveFact,
            }));
            if (isFirstHeadingGlobal) isFirstHeadingGlobal = false;
            return;
          }

          if (NUMBERED_LIST_REGEX.test(trimmed)) {
            flushParagraph();
            if (pendingListType && pendingListType !== 'numbered') flushList();
            pendingListType = 'numbered';
            pendingListItems.push(trimmed);
            return;
          }

          if (BULLET_LIST_REGEX.test(trimmed)) {
            flushParagraph();
            if (pendingListType && pendingListType !== 'bullet') flushList();
            pendingListType = 'bullet';
            pendingListItems.push(trimmed);
            return;
          }

          flushList();
          pendingParagraphLines.push(line);
        });

        flushParagraph();
        flushList();

        return <React.Fragment key={blockIndex}>{elements}</React.Fragment>;
      })}
    </>
  );
};
