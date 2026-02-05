// Shared text highlighting and rendering utilities used by App, PDFViewer, and SearchResultCard
import React from 'react';
import API_BASE_URL, { SEARCH_SEMANTIC_HIGHLIGHTS } from '../config';
import { SearchResult, SummaryModelConfig } from '../types/api';

const API_KEY = process.env.REACT_APP_API_KEY;

export interface TextMatch {
  start: number;
  end: number;
  matchedText: string;
}

export interface SemanticHighlight {
  sentence: string;
  start: number;
  end: number;
  similarity: number;
}

// Find exact phrase matches in text
export const findExactPhraseMatches = (text: string, query: string): TextMatch[] => {
  const matches: TextMatch[] = [];
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase().trim();

  let startIndex = 0;
  while (startIndex < lowerText.length) {
    const index = lowerText.indexOf(lowerQuery, startIndex);
    if (index === -1) break;

    matches.push({
      start: index,
      end: index + lowerQuery.length,
      matchedText: text.substring(index, index + lowerQuery.length)
    });

    startIndex = index + 1; // Continue searching for overlapping matches
  }

  return matches;
};

// Find individual word matches in text
export const findWordMatches = (text: string, query: string): TextMatch[] => {
  const matches: TextMatch[] = [];
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();

  // Common stop words to exclude from highlighting
  const stopWords = new Set([
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
    'to', 'was', 'will', 'with', 'me', 'about', 'tell'
  ]);

  // Split query into words and filter out stop words
  const queryWords = lowerQuery
    .split(/\s+/)
    .filter(word => word.length > 0 && !stopWords.has(word) && word.length > 2);

  if (queryWords.length === 0) return matches;

  // For each query word, find all occurrences
  queryWords.forEach(word => {
    let startIndex = 0;
    while (startIndex < lowerText.length) {
      const index = lowerText.indexOf(word, startIndex);
      if (index === -1) break;

      // Check if this is a word boundary match (not part of a larger word)
      const beforeChar = index > 0 ? lowerText[index - 1] : ' ';
      const afterChar = index + word.length < lowerText.length ? lowerText[index + word.length] : ' ';
      const isWordBoundary = /\W/.test(beforeChar) && /\W/.test(afterChar);

      if (isWordBoundary) {
        matches.push({
          start: index,
          end: index + word.length,
          matchedText: text.substring(index, index + word.length)
        });
      }

      startIndex = index + 1;
    }
  });

  // Sort by start position and remove duplicates
  return matches
    .sort((a, b) => a.start - b.start)
    .filter((match, idx, arr) =>
      idx === 0 || match.start !== arr[idx - 1].start
    );
};

// Expand matches to include complete phrases (mimics PDF span-based highlighting)
export const expandMatchesToPhrases = (text: string, matches: TextMatch[]): TextMatch[] => {
  if (matches.length === 0) return matches;

  const expandedMatches: TextMatch[] = [];

  matches.forEach(match => {
    let start = match.start;
    let end = match.end;

    // Expand backwards to start of phrase/sentence (stop at punctuation or whitespace clusters)
    while (start > 0) {
      const char = text[start - 1];
      // Stop at sentence boundaries or multiple spaces
      if (/[.!?;:\n]/.test(char)) break;
      // Stop at double spaces (paragraph boundaries)
      if (char === ' ' && start > 1 && text[start - 2] === ' ') break;
      start--;
    }

    // Expand forward to end of phrase/sentence
    while (end < text.length) {
      const char = text[end];
      // Stop at sentence boundaries
      if (/[.!?;:\n]/.test(char)) {
        end++; // Include the punctuation
        break;
      }
      // Stop at double spaces
      if (char === ' ' && end < text.length - 1 && text[end + 1] === ' ') break;
      end++;
    }

    // Trim leading/trailing whitespace from expanded match
    while (start < end && /\s/.test(text[start])) start++;
    while (end > start && /\s/.test(text[end - 1])) end--;

    if (start < end) {
      expandedMatches.push({
        start,
        end,
        matchedText: text.substring(start, end)
      });
    }
  });

  // Merge overlapping expanded matches
  if (expandedMatches.length === 0) return expandedMatches;

  const merged: TextMatch[] = [];
  const sorted = expandedMatches.sort((a, b) => a.start - b.start);
  let current = sorted[0];

  for (let i = 1; i < sorted.length; i++) {
    // If this match overlaps or is very close to current, merge them
    if (sorted[i].start <= current.end + 2) {
      current.end = Math.max(current.end, sorted[i].end);
      current.matchedText = text.substring(current.start, current.end);
    } else {
      merged.push(current);
      current = sorted[i];
    }
  }
  merged.push(current);

  return merged;
};

// Combine phrase and word matches with proper priority
export const findAllMatches = (text: string, query: string): TextMatch[] => {
  if (!query.trim()) return [];

  // First try exact phrase matches
  let matches = findExactPhraseMatches(text, query);

  if (matches.length === 0) {
    // Fallback to word matches
    matches = findWordMatches(text, query);
  }

  // For keyword highlighting, return exact matches only (no sentence expansion)
  // Only semantic matches should highlight full sentences
  return matches;
};

// Helper to normalize to alphanumeric only for robust comparison
const normalizeAlphanumeric = (str: string) => str.toLowerCase().replace(/[^a-z0-9]/g, '');

// Unified highlighting using backend API
// Returns the full response object now
export const highlightTextWithAPI = async (
  text: string,
  query: string,
  highlightType: 'keyword' | 'semantic' | 'both' = 'both',
  threshold: number = 0.4,
  semanticModelConfig?: SummaryModelConfig | null
): Promise<any> => {
  if (!query.trim() || !text.trim()) return { highlighted_text: text, matches: [] };

  try {
    const response = await fetch(`${API_BASE_URL}/highlight`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(API_KEY ? { 'X-API-Key': API_KEY } : {})
      },
      body: JSON.stringify({
        query: query.trim(),
        text: text,
        highlight_type: highlightType,
        semantic_threshold: threshold,
        semantic_model_config: semanticModelConfig || undefined
      })
    });

    if (!response.ok) {
      console.error('Highlighting failed:', response.statusText);
      return { highlighted_text: text, matches: [] };
    }

    const data = await response.json();
    console.log('Backend Highlight Response:', data);
    return data;
  } catch (error) {
    console.error('Highlighting error:', error);
    return { highlighted_text: text, matches: [] };
  }
};

// Helper to escape regex special characters
const escapeRegExp = (string: string) => {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
};

const extractUniquePhrases = (matches: any[]): string[] => {
  const phrases = matches
    .map((match: any) => match.text?.trim())
    .filter((text: any) => text && text.length > 0);
  return Array.from(new Set(phrases)) as string[];
};

const buildPhraseRegex = (phrase: string): RegExp => {
  const escapedText = escapeRegExp(phrase);
  const pattern = escapedText.replace(/\s+/g, '\\s+');
  return new RegExp(pattern, 'gi');
};

const collectPhraseRanges = (
  text: string,
  phrases: string[]
): { start: number; end: number; phrase: string }[] => {
  const foundRanges: { start: number; end: number; phrase: string }[] = [];

  for (const phrase of phrases) {
    const regex = buildPhraseRegex(phrase);
    let match;
    while ((match = regex.exec(text)) !== null) {
      console.log(`[SemanticDebug] Found match for '${phrase}' at ${match.index}: '${match[0]}'`);
      foundRanges.push({
        start: match.index,
        end: match.index + match[0].length,
        phrase: phrase
      });
    }
  }

  return foundRanges;
};

const mergePhraseRanges = (
  text: string,
  ranges: { start: number; end: number; phrase: string }[]
): TextMatch[] => {
  if (ranges.length === 0) {
    return [];
  }

  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  const mergedMatches: TextMatch[] = [];
  let current = sorted[0];

  for (let i = 1; i < sorted.length; i++) {
    const next = sorted[i];

    if (next.start < current.end) {
      current.end = Math.max(current.end, next.end);
      console.log(
        `[SemanticDebug] Merging overlap: [${current.start}-${current.end}] with [${next.start}-${next.end}]`
      );
    } else {
      mergedMatches.push({
        start: current.start,
        end: current.end,
        matchedText: text.substring(current.start, current.end)
      });
      current = next;
    }
  }

  mergedMatches.push({
    start: current.start,
    end: current.end,
    matchedText: text.substring(current.start, current.end)
  });

  return mergedMatches;
};

const shouldLogSemanticDebug = (text: string): boolean => text.includes('Health and Safety');

const expandToWordBoundaries = (text: string, start: number, end: number) => {
  const isWordChar = (char: string) => /\w/.test(char);

  let startIndex = start;
  let endIndex = end;

  while (startIndex > 0 && isWordChar(text[startIndex - 1])) {
    startIndex--;
  }
  while (endIndex < text.length && isWordChar(text[endIndex])) {
    endIndex++;
  }

  return { start: startIndex, end: endIndex };
};

const getSemanticLocalMatches = (
  text: string,
  semanticMatches: Array<{ matchedText: string }>
): Array<{ start: number; end: number; similarity?: number }> => {
  const uniquePhrases = Array.from(
    new Set(semanticMatches.map((match) => match.matchedText).filter(Boolean))
  ).map((phrase) => phrase.trim()).filter(Boolean);

  if (shouldLogSemanticDebug(text)) {
    console.log(
      `[RenderHighlight] Processing text segment (len=${text.length}): "${text.substring(0, 50)}..."`
    );
    console.log('[RenderHighlight] Unique phrases to match:', uniquePhrases);
  }

  const localMatches: Array<{ start: number; end: number; similarity?: number }> = [];

  uniquePhrases.forEach((phrase) => {
    const regex = buildPhraseRegex(phrase);
    let match;
    while ((match = regex.exec(text)) !== null) {
      const bounds = expandToWordBoundaries(text, match.index, match.index + match[0].length);
      localMatches.push({
        start: bounds.start,
        end: bounds.end,
        similarity: 1.0
      });
    }
  });

  if (shouldLogSemanticDebug(text)) {
    console.log('[RenderHighlight] Local matches found:', localMatches);
  }

  return localMatches;
};

const shouldSkipHighlighting = (
  text: string,
  matches: Array<{ start: number; end: number }>,
  semanticEnabled: boolean
): boolean => {
  const totalHighlightedLength = matches.reduce((sum, match) => sum + (match.end - match.start), 0);
  const highlightPercentage = (totalHighlightedLength / text.length) * 100;
  const limit = semanticEnabled ? 90 : 50;

  if (highlightPercentage > limit) {
    if (shouldLogSemanticDebug(text)) {
      console.log(
        `[RenderHighlight] Rejected due to density: ${highlightPercentage.toFixed(2)}% > ${limit}% (Total highlight len: ${totalHighlightedLength})`
      );
    }
    return true;
  }

  return false;
};

const normalizeMatches = (
  matches: Array<{ start: number; end: number; similarity?: number }>
): Array<{ start: number; end: number; similarity?: number }> => (
  matches
    .sort((a, b) => a.start - b.start)
    .filter((match, idx, arr) => {
      if (idx === 0) return true;
      const prevMatch = arr[idx - 1];
      return match.start >= prevMatch.end;
    })
);

const buildHighlightedParts = (
  text: string,
  matches: Array<{ start: number; end: number; similarity?: number }>,
  keyPrefix: string
): React.ReactNode[] => {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  matches.forEach((match, idx) => {
    if (match.start > lastIndex) {
      parts.push(text.substring(lastIndex, match.start));
    }
    const highlightTitle = match.similarity ? `Similarity: ${match.similarity.toFixed(2)}` : undefined;
    parts.push(
      <mark key={`${keyPrefix}-${idx}`} className="search-highlight" title={highlightTitle}>
        {text.substring(match.start, match.end)}
      </mark>
    );
    lastIndex = match.end;
  });

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return parts;
};

export const findSemanticMatches = async (
  text: string,
  query: string,
  threshold: number = 0.4,
  semanticModelConfig?: SummaryModelConfig | null
): Promise<TextMatch[]> => {
  if (!query.trim() || !text.trim()) return [];

  // Get full response from API
  const responseData = await highlightTextWithAPI(
    text,
    query,
    'semantic',
    threshold,
    semanticModelConfig
  );

  if (!responseData || !responseData.matches || !Array.isArray(responseData.matches)) {
    return [];
  }

  // 1. Extract unique phrases from backend matches
  const uniquePhrases = extractUniquePhrases(responseData.matches);

  console.log('[SemanticDebug] Unique Phrases extracted:', uniquePhrases);
  console.log('[SemanticDebug] All Backend Matches:', responseData.matches);

  // 2. Find ALL instances of each unique phrase in the text
  // We use a regex that treats whitespace flexibly to handle differences between backend/frontend rendering
  const foundRanges = collectPhraseRanges(text, uniquePhrases);

  // 3. Merge overlapping ranges to prevent rendering issues
  const mergedMatches = mergePhraseRanges(text, foundRanges);

  console.log(`Global Phrase Match found ${mergedMatches.length} ranges for ${uniquePhrases.length} unique phrases.`);
  return mergedMatches;
};

// Helper function to handle indentation and list markers for display
export const formatLinesWithIndentation = (
  nodes: React.ReactNode[],
  context?: { lastType: 'none' | 'number' | 'bullet' | 'letter'; level: number }
): React.ReactNode => {
  // If no nodes, return empty (never return null to avoid React errors with children)
  if (!nodes || nodes.length === 0) return <span />;

  const lines = splitNodesIntoLines(nodes);

  // If no lines were created (e.g. empty string), return empty span
  if (lines.length === 0) return <span />;

  // Default context if not provided
  let lastType: 'none' | 'number' | 'bullet' | 'letter' = context?.lastType || 'none';
  // Use a default indention if we see a list marker at the start
  let currentIndentLevel = context?.level || 0;

  return (
    <div className="formatted-text-block">
      {lines.map((line, idx) => {
        const { type, markerMatch } = getLineMarkerInfo(line);
        currentIndentLevel = computeIndentLevel(currentIndentLevel, lastType, type);

        const isEmpty = isLineEmpty(line);
        lastType = updateLineContext(context, lastType, currentIndentLevel, type, isEmpty);

        if (type !== 'none' && markerMatch && !isEmpty) {
          const { marker, contentNodes } = stripLineMarker(line, markerMatch);
          return renderListLine(marker, contentNodes, currentIndentLevel, idx);
        }

        return renderStandardLine(line, type, currentIndentLevel, isEmpty, idx);
      })}
    </div>
  );
};

const splitNodesIntoLines = (nodes: React.ReactNode[]): React.ReactNode[][] => {
  const lines: React.ReactNode[][] = [];
  let currentLine: React.ReactNode[] = [];

  const processNode = (node: React.ReactNode) => {
    if (typeof node === 'string') {
      const parts = node.split('\n');
      parts.forEach((part, index) => {
        if (index > 0) {
          if (currentLine.length > 0) {
            lines.push(currentLine);
          } else {
            lines.push(['']);
          }
          currentLine = [];
        }
        if (part) {
          currentLine.push(part);
        }
      });
    } else {
      currentLine.push(node);
    }
  };

  nodes.forEach(processNode);
  if (currentLine.length > 0) {
    lines.push(currentLine);
  }

  return lines;
};

const getLineMarkerInfo = (line: React.ReactNode[]) => {
  let type: 'none' | 'number' | 'bullet' | 'letter' = 'none';
  let markerMatch: RegExpMatchArray | null = null;

  const firstNode = line[0];
  if (typeof firstNode === 'string') {
    const trimmed = firstNode.trimStart();

    if (/^(?:-|\*|\u2022)\s+/.test(trimmed)) {
      type = 'bullet';
      markerMatch = trimmed.match(/^(?:-|\*|\u2022)\s+/);
    } else if (/^\d+[\.)]\s+/.test(trimmed)) {
      type = 'number';
      markerMatch = trimmed.match(/^\d+[\.)]\s+/);
    } else if (/^\s*[a-zA-Z]\.\s+/.test(trimmed)) {
      type = 'letter';
      markerMatch = trimmed.match(/^\s*[a-zA-Z]\.\s+/);
    }
  }

  return { type, markerMatch };
};

const computeIndentLevel = (
  currentIndentLevel: number,
  lastType: 'none' | 'number' | 'bullet' | 'letter',
  type: 'none' | 'number' | 'bullet' | 'letter'
): number => {
  if (type === 'none') {
    return currentIndentLevel;
  }
  if (lastType === 'none') {
    return 1;
  }
  if (type === 'number') {
    return lastType !== 'number' ? 1 : currentIndentLevel;
  }
  if (lastType === 'number') {
    return currentIndentLevel + 2;
  }
  return currentIndentLevel;
};

const isLineEmpty = (line: React.ReactNode[]): boolean =>
  line.every((node) => !node || (typeof node === 'string' && node.trim() === ''));

const updateLineContext = (
  context: { lastType: 'none' | 'number' | 'bullet' | 'letter'; level: number } | undefined,
  lastType: 'none' | 'number' | 'bullet' | 'letter',
  currentIndentLevel: number,
  type: 'none' | 'number' | 'bullet' | 'letter',
  isEmpty: boolean
): 'none' | 'number' | 'bullet' | 'letter' => {
  if (context) {
    context.level = currentIndentLevel;
  }

  if (!isEmpty) {
    const nextType = type;
    if (context) {
      context.lastType = nextType;
    }
    return nextType;
  }

  return lastType;
};

const stripLineMarker = (line: React.ReactNode[], markerMatch: RegExpMatchArray) => {
  const marker = markerMatch[0];
  const contentNodes = [...line];
  if (typeof contentNodes[0] === 'string') {
    contentNodes[0] = contentNodes[0].substring(marker.length);
  }
  return { marker, contentNodes };
};

const renderListLine = (
  marker: string,
  contentNodes: React.ReactNode[],
  indentLevel: number,
  idx: number
) => (
  <div
    key={idx}
    style={{
      display: 'flex',
      flexDirection: 'row',
      paddingLeft: Math.max(0, (indentLevel - 1) * 1.5) + 'em',
      minHeight: 'auto',
    }}
  >
    <div style={{ minWidth: '1.5em', flexShrink: 0 }}>{marker}</div>
    <div>{contentNodes}</div>
  </div>
);

const renderStandardLine = (
  line: React.ReactNode[],
  type: 'none' | 'number' | 'bullet' | 'letter',
  indentLevel: number,
  isEmpty: boolean,
  idx: number
) => (
  <div
    key={idx}
    style={{
      paddingLeft: (type !== 'none' ? Math.max(0, indentLevel * 1.5) : 0) + 'em',
      textIndent: type !== 'none' ? '-1.5em' : '0',
      minHeight: isEmpty ? '1em' : 'auto',
    }}
  >
    {line}
  </div>
);

// Helper to parse superscripts from text into an array of nodes (strings and sup elements)
export const parseSuperscripts = (text: string): React.ReactNode[] => {
  if (!text) return [];

  // Use a regex that captures the number from various formats:
  // [^N], [^N]:, [N], ^N
  const regex = /(?:\[\^(\d+)\]:?)|(?:\[(\d+)\])|(?:\^(\d+))/g;

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    // Extract the number (from whichever group matched)
    const num = match[1] || match[2] || match[3];

    parts.push(
      <sup key={`${match.index}-${num}`} className="reference-number">
        {num}
      </sup>
    );

    lastIndex = regex.lastIndex;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
};

// Helper to render text with regex-based superscripts (standard rendering)
// Updated to strip brackets and colons from standardized citations [^N]
export const parseAndRenderSuperscripts = (text: string, context?: { lastType: 'none' | 'number' | 'bullet' | 'letter'; level: number }): React.ReactNode => {
  const parts = parseSuperscripts(text);
  return formatLinesWithIndentation(parts, context);
};

type InlineReferencePattern = 'geometric_caret' | 'bracket_caret' | 'square_bracket';

const buildSuperscriptedHighlightNodes = (
  chunk: string,
  query: string | undefined,
  semanticMatches: Array<{ start: number; end: number; similarity?: number }> | undefined,
  chunkCounterRef: { value: number }
): React.ReactNode[] => {
  const mockResult = semanticMatches ? { semanticMatches } as SearchResult : undefined;
  const uniquePrefix = `highlight-${chunkCounterRef.value++}`;
  const highlightedNodes = renderHighlightedText(chunk, query || '', mockResult, uniquePrefix);

  return highlightedNodes.map((node) => {
    if (typeof node === 'string') {
      return parseSuperscripts(node);
    }
    if (React.isValidElement(node) && node.type === 'mark') {
      const nodeElement = node as React.ReactElement<{ children?: string }>;
      const children = nodeElement.props.children;
      if (typeof children === 'string') {
        return React.cloneElement(nodeElement, {}, parseSuperscripts(children));
      }
    }
    return node;
  }).flat();
};

const detectInlineReferencePattern = (
  text: string,
  position: number
): { splitPos: number; pattern: InlineReferencePattern | null } => {
  if (position >= 2 && text.slice(position - 2, position) === '[^') {
    return { splitPos: position - 2, pattern: 'bracket_caret' };
  }
  if (position >= 1 && text[position - 1] === '[') {
    return { splitPos: position - 1, pattern: 'square_bracket' };
  }
  if (position >= 1 && text[position - 1] === '^') {
    return { splitPos: position - 1, pattern: 'geometric_caret' };
  }
  return { splitPos: position, pattern: null };
};

const stripReferenceSuffix = (text: string, pattern: InlineReferencePattern | null): string => {
  let cleaned = text;
  if (pattern === 'bracket_caret' && cleaned.startsWith(']')) {
    cleaned = cleaned.slice(1);
    if (cleaned.startsWith(':')) cleaned = cleaned.slice(1);
  } else if (pattern === 'square_bracket' && cleaned.startsWith(']')) {
    cleaned = cleaned.slice(1);
  }
  return cleaned;
};

const buildReferenceNode = (number: number, position: number) => (
  <sup key={`ref-${number}-${position}`} className="inline-reference-number">
    {number}
  </sup>
);

// Helper function to render text with inline references as superscript (NO highlighting)
export const renderTextWithInlineReferences = (
  text: string,
  query?: string,
  inlineRefs?: Array<{ number: number; position: number; pattern: string }>,
  semanticMatches?: Array<{ start: number; end: number; similarity?: number }>,
  context?: { lastType: 'none' | 'number' | 'bullet' | 'letter'; level: number }
): React.ReactNode => {
  // Sort references by position (descending) to process from end to start
  const sortedRefs = inlineRefs ? [...inlineRefs].sort((a, b) => b.position - a.position) : [];

  const parts: React.ReactNode[] = [];
  let remainingText = text;

  const chunkCounterRef = { value: 0 };
  const processTextChunk = (chunk: string) =>
    buildSuperscriptedHighlightNodes(chunk, query, semanticMatches, chunkCounterRef);

  // Process each reference from end to start (to preserve indices)
  for (const ref of sortedRefs) {
    const { number, position, pattern } = ref;

    // Extract text after this reference
    const afterRef = remainingText.slice(position);

    // Find the reference number in the text
    const numStr = number.toString();
    const numLength = numStr.length;

    // Check if number matches at position
    if (afterRef.startsWith(numStr)) {
      const { splitPos, pattern } = detectInlineReferencePattern(remainingText, position);
      const beforeRef = remainingText.slice(0, splitPos);
      const afterNum = stripReferenceSuffix(afterRef.slice(numLength), pattern);

      // Add part after number
      if (afterNum) {
        parts.unshift(...processTextChunk(afterNum));
      }

      // Add the reference number
      parts.unshift(buildReferenceNode(number, position));

      // Update remaining text
      remainingText = beforeRef;
    }
  }

  // Add any remaining text at the start
  if (remainingText) {
    parts.unshift(...processTextChunk(remainingText));
  }

  // Return parts formatted with indentation
  return formatLinesWithIndentation(parts, context);
};



// Render text with highlighting (replaces local highlightText in App.tsx)
export const renderHighlightedText = (
  text: string,
  query: string,
  result?: SearchResult,
  keyPrefix: string = 'highlight'
): React.ReactNode[] => {
  if (!query.trim()) return [text];

  let matches: Array<{ start: number, end: number, similarity?: number }> = [];
  const semanticEnabled = SEARCH_SEMANTIC_HIGHLIGHTS && Boolean(result?.semanticMatches);

  // Step 1: Check if Semantic Highlighting is enabled
  if (semanticEnabled && result?.semanticMatches) {
    // Semantic Mode:
    // The matches in result.semanticMatches are calculated against the FULL document text.
    // However, this function is often called on partial text (e.g., individual elements/paragraphs).
    // Using global offsets on partial text causes "shredded" highlights.
    // SOLUTION: Extract the unique phrases found by the backend and re-match them LOCALLY against the current text segment.
    matches = getSemanticLocalMatches(text, result.semanticMatches);
  }
  // Step 2: Fallback to keyword highlighting if semantic is disabled or no matches
  else if (!SEARCH_SEMANTIC_HIGHLIGHTS) {
    const allMatches = findAllMatches(text, query);
    matches = allMatches.map(m => ({ ...m, similarity: undefined }));
  }

  if (matches.length === 0) {
    return [text];
  }

  if (shouldSkipHighlighting(text, matches, semanticEnabled)) {
    return [text];
  }

  matches = normalizeMatches(matches);
  return buildHighlightedParts(text, matches, keyPrefix);
};

// Helper to render basic markdown (bold, italic) in text
export const renderMarkdownText = (text: string): React.ReactNode => {
  // Handle **bold**
  let result: React.ReactNode = text;
  const boldRegex = /\*\*(.+?)\*\*/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;

  while ((match = boldRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index));
    }
    parts.push(<strong key={`bold-${match.index}`}>{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  if (parts.length > 0) {
    // Now handle *italic* in each part
    return parts.map((part, idx) => {
      if (typeof part === 'string') {
        const italicParts: React.ReactNode[] = [];
        const italicRegex = /\*(.+?)\*/g;
        let lastItalicIndex = 0;
        let italicMatch;

        while ((italicMatch = italicRegex.exec(part)) !== null) {
          if (italicMatch.index > lastItalicIndex) {
            italicParts.push(part.substring(lastItalicIndex, italicMatch.index));
          }
          italicParts.push(<em key={`italic-${idx}-${italicMatch.index}`}>{italicMatch[1]}</em>);
          lastItalicIndex = italicMatch.index + italicMatch[0].length;
        }

        if (lastItalicIndex < part.length) {
          italicParts.push(part.substring(lastItalicIndex));
        }

        return italicParts.length > 0 ? <React.Fragment key={idx}>{italicParts}</React.Fragment> : part;
      }
      return <React.Fragment key={idx}>{part}</React.Fragment>;
    });
  }

  return result;
};
