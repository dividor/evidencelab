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
const BULLET_LIST_REGEX = /^\*\s/;

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

const getListType = (lines: string[]): 'numbered' | 'bullet' | 'paragraph' => {
  const isNumberedList = lines.some((line) => NUMBERED_LIST_REGEX.test(line.trim()));
  if (isNumberedList) return 'numbered';
  const isBulletList = lines.some((line) => BULLET_LIST_REGEX.test(line.trim()));
  return isBulletList ? 'bullet' : 'paragraph';
};

const stripListPrefix = (line: string, listType: 'numbered' | 'bullet'): string => {
  if (listType === 'numbered') {
    return line.replace(NUMBERED_LIST_REGEX, '');
  }
  return line.trim().replace(BULLET_LIST_REGEX, '');
};

const buildCitationLinkTitle = (result: SearchResult): string =>
  `${result.title} (${result.organization || 'Unknown'}${result.year ? `, ${result.year}` : ''})`;

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
        const listType = getListType(lines);

        if (listType === 'numbered' || listType === 'bullet') {
          const ListTag: React.ElementType = listType === 'numbered' ? 'ol' : 'ul';

          return (
            <ListTag key={blockIndex}>
              {lines.map((line, lineIndex) => {
                const content = stripListPrefix(line, listType);
                if (!content.trim()) return null;
                return (
                  <li key={lineIndex}>
                    {renderLineWithCitations(
                      content,
                      searchResults,
                      citationMapping,
                      onResultClick,
                      `${blockIndex}-${lineIndex}`
                    )}
                  </li>
                );
              })}
            </ListTag>
          );
        }

        return (
          <p key={blockIndex}>
            {renderLineWithCitations(
              block,
              searchResults,
              citationMapping,
              onResultClick,
              `${blockIndex}-0`
            )}
          </p>
        );
      })}
    </>
  );
};
