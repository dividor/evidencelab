import React from 'react';
import { SearchResult } from '../types/api';
import { renderMarkdownText } from '../utils/textHighlighting';

interface AiSummaryWithCitationsProps {
  summaryText: string;
  searchResults: SearchResult[];
  onResultClick: (result: SearchResult) => void;
}

const CITATION_REGEX = /\[(\d+(?:,\s*\d+)*)\]/g;
const NUMBERED_LIST_REGEX = /^\d+[\.)]\s/;
const BULLET_LIST_REGEX = /^[-*]\s/;
const HEADING_REGEX = /^(#{1,4})\s+(.+)$/;

const parseCitationNumbers = (rawNumbers: string): number[] =>
  rawNumbers.split(',').map((item) => parseInt(item.trim(), 10));

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


const stripListPrefix = (line: string, listType: 'numbered' | 'bullet'): string => {
  if (listType === 'numbered') {
    return line.replace(NUMBERED_LIST_REGEX, '');
  }
  return line.trim().replace(/^[-*]\s/, '');
};

const buildCitationLinkTitle = (result: SearchResult): string => {
  const yearSuffix = result.year ? ', ' + result.year : '';
  return result.title + ' (' + (result.organization || 'Unknown') + yearSuffix + ')';
};

const renderCitationLinks = (
  rawNumbers: string,
  searchResults: SearchResult[],
  citationMapping: Map<number, number>,
  onResultClick: (result: SearchResult) => void,
  keyPrefix: string
): React.ReactNode[] => {
  const originalNumbers = parseCitationNumbers(rawNumbers);
  const links: React.ReactNode[] = [];

  originalNumbers.forEach((originalNumber, idx) => {
    const sequentialNumber = citationMapping.get(originalNumber);
    if (sequentialNumber === undefined) return;

    const citationIndex = originalNumber - 1;
    const result =
      citationIndex >= 0 && citationIndex < searchResults.length
        ? searchResults[citationIndex]
        : null;

    if (result) {
      links.push(
        <a
          key={`${keyPrefix}-link-${sequentialNumber}-${idx}`}
          href="#"
          className="ai-summary-citation"
          onClick={(event: React.MouseEvent) => {
            event.preventDefault();
            onResultClick(result);
          }}
          title={buildCitationLinkTitle(result)}
        >
          {sequentialNumber}
        </a>
      );
    } else {
      links.push(
        <span key={`${keyPrefix}-missing-${sequentialNumber}-${idx}`}>
          {sequentialNumber}
        </span>
      );
    }

    if (idx < originalNumbers.length - 1) {
      links.push(<span key={`${keyPrefix}-sep-${sequentialNumber}-${idx}`}>, </span>);
    }
  });

  return links;
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
          [{citationLinks}]
        </span>
      );
    }
    return <React.Fragment key={`${keyPrefix}-text-${idx}`}>{renderMarkdownText(segment)}</React.Fragment>;
  });

  return <>{parts}</>;
};

export const AiSummaryWithCitations: React.FC<AiSummaryWithCitationsProps> = ({
  summaryText,
  searchResults,
  onResultClick,
}) => {
  const citationMapping = buildCitationMapping(summaryText);
  const blocks = splitSummaryBlocks(summaryText);

  return (
    <>
      {blocks.map((block, blockIndex) => {
        if (!block.trim()) return null;
        const lines = block.split(/\n/);

        // Render each line according to its type, grouping consecutive
        // lines of the same kind into a single element.
        const elements: React.ReactNode[] = [];
        let pendingParagraphLines: string[] = [];
        let pendingListItems: string[] = [];
        let pendingListType: 'numbered' | 'bullet' | null = null;

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
          elements.push(
            <ListTag key={`${blockIndex}-list-${elements.length}`}>
              {pendingListItems.map((item, li) => (
                <li key={li}>
                  {renderLineWithCitations(stripListPrefix(item, lt), searchResults, citationMapping, onResultClick, `${blockIndex}-${elements.length}-${li}`)}
                </li>
              ))}
            </ListTag>
          );
          pendingListItems = [];
          pendingListType = null;
        };

        lines.forEach((line) => {
          const trimmed = line.trim();
          if (!trimmed) return;

          const headingMatch = trimmed.match(HEADING_REGEX);
          if (headingMatch) {
            flushParagraph();
            flushList();
            const content = renderLineWithCitations(headingMatch[2], searchResults, citationMapping, onResultClick, `${blockIndex}-h-${elements.length}`);
            const level = Math.min(headingMatch[1].length + 2, 6);
            elements.push(React.createElement(`h${level}`, { key: `${blockIndex}-h-${elements.length}` }, content));
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
