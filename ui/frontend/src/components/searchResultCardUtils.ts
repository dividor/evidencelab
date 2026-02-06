import { SearchResult, ChunkElement, ElementData } from '../types/api';

const MIN_IMAGE_AREA = 10000;
const CAPTION_KEYWORDS = ['figure', 'table', 'diagram'];

const collectTextBBoxesByPage = (elements: ElementData[]) => {
  const bboxesByPage: Record<number, Array<{ minY: number; maxY: number }>> = {};

  elements.forEach((element) => {
    if (!element.bbox || element.bbox.length < 4 || typeof element.page !== 'number') {
      return;
    }

    const [_, minY, __, maxY] = element.bbox;
    if (typeof minY !== 'number' || typeof maxY !== 'number') {
      return;
    }

    if (!bboxesByPage[element.page]) {
      bboxesByPage[element.page] = [];
    }
    bboxesByPage[element.page].push({ minY, maxY });
  });

  return bboxesByPage;
};

const hasCaptionKeywords = (elements: ElementData[]) =>
  elements.some((element) => {
    const text = element.text?.trim().toLowerCase() || '';
    return CAPTION_KEYWORDS.some((keyword) => text.startsWith(keyword));
  });

const shouldIncludeImage = (
  imgBBox: number[],
  textBBoxes: Array<{ minY: number; maxY: number }>,
  hasCaptions: boolean
) => {
  const imgMinY = imgBBox[1];
  const imgMaxY = imgBBox[3];
  const tolerance = hasCaptions ? 800 : 0;

  return textBBoxes.some(({ minY, maxY }) => {
    const minWithTolerance = minY - tolerance;
    const maxWithTolerance = maxY + tolerance;
    return !(imgMaxY < minWithTolerance || imgMinY > maxWithTolerance);
  });
};

const buildTableText = (rows: Array<Array<{ text?: string }>>) =>
  rows
    .flatMap((row) => row.map((cell) => cell.text || ''))
    .join(' ')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();

const normalizeSnippetText = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^\w\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();


// Extracts things like "Figure 2", "Graph 12", "Table 4.1" from text
const extractCaptionReferences = (text: string): string[] => {
  if (!text) return [];
  // Matches "Figure 2", "Figure 2.1", "Table 10", "Graph 5", "Map 3"
  // Case insensitive
  const regex = /\b(figure|table|graph|map)\s+(\d+(?:\.\d+)?)\b/gi;
  const matches = text.match(regex);
  return matches ? matches.map(m => m.toLowerCase().replace(/\s+/g, ' ').replace(/\.$/, '')) : [];
};

const normalizeCaption = (caption: string): string =>
  caption.toLowerCase().replace(/[^\w\s\d]/g, '').replace(/\s+/g, ' ').trim();
export const isTextRedundantWithTable = (text: string, tableData: any): boolean => {
  if (!tableData?.rows || !text) {
    return false;
  }

  const tableText = buildTableText(tableData.rows);
  const normalizedSnippet = normalizeSnippetText(text);
  const snippetWords = normalizedSnippet.split(' ').filter((word) => word.length > 3);
  if (snippetWords.length === 0) {
    return false;
  }

  const matchedWords = snippetWords.filter((word) => tableText.includes(word));
  const matchPercentage = matchedWords.length / snippetWords.length;
  return matchPercentage > 0.8;
};

export const shouldShowSnippetText = (result: SearchResult, snippetText: string) => {
  const hasTable = result.item_types?.includes('TableItem') && result.table_data?.image_path;
  return !hasTable || !isTextRedundantWithTable(snippetText, result.table_data);
};

const collectChunkTextBBoxesByPage = (elements: ChunkElement[]) => {
  const bboxesByPage: Record<number, Array<{ minY: number; maxY: number }>> = {};

  elements.forEach((element) => {
    if (element.element_type !== 'text') {
      return;
    }
    if (!element.bbox || element.bbox.length < 4 || typeof element.page !== 'number') {
      return;
    }

    const [_, minY, __, maxY] = element.bbox;
    if (typeof minY !== 'number' || typeof maxY !== 'number') {
      return;
    }

    if (!bboxesByPage[element.page]) {
      bboxesByPage[element.page] = [];
    }
    bboxesByPage[element.page].push({ minY, maxY });
  });

  return bboxesByPage;
};

const hasChunkCaptionKeywords = (elements: ChunkElement[]) =>
  elements.some((element) => {
    if (element.element_type !== 'text') {
      return false;
    }
    const text = element.text?.trim().toLowerCase() || '';
    return CAPTION_KEYWORDS.some((keyword) => text.startsWith(keyword));
  });

const filterChunkVisualsByTextOverlap = (elements: ChunkElement[], anchorPage?: number, pageTolerance: number = 1) => {
  const textBBoxesByPage = collectChunkTextBBoxesByPage(elements);
  const hasCaptions = hasChunkCaptionKeywords(elements);
  const pagesWithText = Object.keys(textBBoxesByPage).length > 0;

  return elements.filter((element) => {
    if (element.element_type === 'table') {
      return !(anchorPage && anchorPage > 0 && Math.abs(element.page - anchorPage) > pageTolerance);
    }

    if (element.element_type !== 'image') {
      return true;
    }

    // Check if image is referenced in any text chunk
    // If explicitly referenced, we KEEP it regardless of page distance
    const isReferenced = elements.some(el =>
      el.element_type === 'text' &&
      el.text &&
      isImageReferencedInText(element, el.text)
    );

    if (isReferenced) {
      return true;
    }

    // Filter out images that are not on the current, previous, or following pages relative to the result anchor
    if (anchorPage && anchorPage > 0 && Math.abs(element.page - anchorPage) > pageTolerance) {
      return false;
    }

    if (!pagesWithText || !element.bbox || element.bbox.length < 4) {
      // If we are here, it means we are within page tolerance, but invalid bbox or no text pages.
      // Strict filter: if no text pages, remove visual? Or keep?
      // original logic: return false
      return false;
    }

    if (typeof element.page !== 'number' || !textBBoxesByPage[element.page]) {
      return false;
    }

    return shouldIncludeImage(element.bbox, textBBoxesByPage[element.page], hasCaptions);
  });
};

const isImageReferencedInText = (
  image: ChunkElement | ElementData,
  snippetText: string
): boolean => {
  const refs = extractCaptionReferences(snippetText);
  if (refs.length === 0) return false;

  const imagePath = (image as any).path || (image as any).image_path || '';
  if (!imagePath) return false;

  // Extract number/id from path, e.g. "/.../fig2.png" -> "2", "/.../table_4.1.png" -> "4.1"
  // This is a heuristic.
  const filename = imagePath.split('/').pop()?.toLowerCase() || '';

  // Clean filename to remove extension and "fig", "table" prefixes if present in filename
  // e.g. "fig2.png" -> "2", "figure-2.jpg" -> "2"
  const cleanName = filename.replace(/\.[^/.]+$/, "").replace(/^(figure|fig|table|graph|map)[-_.\s]*/, "");

  return refs.some(ref => {
    // ref is like "figure 2" or "table 4.1"
    // we check if the ref's number part matches our cleanName
    const refParts = ref.split(' ');
    const refNum = refParts[1]; // "2"
    return cleanName === refNum;
  });
};

const addChunkElements = (
  result: SearchResult,
  orderedElements: Array<ChunkElement & { key: string }>
) => {
  if (!result.chunk_elements || result.chunk_elements.length === 0) {
    return;
  }

  const filteredElements = filterChunkVisualsByTextOverlap(result.chunk_elements, result.page_num, 1);

  filteredElements.forEach((el, idx) => {
    // ...
    orderedElements.push({
      ...el,
      element_type: el.element_type,
      key: `element-${idx}`
    });
  });
};

const addLegacyTextElements = (
  result: SearchResult,
  orderedElements: Array<ChunkElement & { key: string }>
) => {
  if (result.elements && result.elements.length > 0) {
    result.elements.forEach((el, idx) => {
      if (el.type === 'TextItem' && el.text) {
        orderedElements.push({
          element_type: 'text',
          text: el.text,
          label: el.label,
          page: el.page,
          position_hint: el.position_hint || 0,
          key: `element-text-${idx}`
        });
      }
    });
    return;
  }

  if (result.text) {
    orderedElements.push({
      element_type: 'text',
      text: result.text,
      label: 'text',
      page: result.page_num || 0,
      position_hint: 0,
      key: 'element-text-fallback'
    });
  }
};

const addLegacyImageElements = (
  result: SearchResult,
  orderedElements: Array<ChunkElement & { key: string }>
) => {
  if (!result.images || !result.elements || result.elements.length === 0) {
    return;
  }

  const textBBoxesByPage = collectTextBBoxesByPage(result.elements);
  const hasCaptions = hasCaptionKeywords(result.elements);

  result.images.forEach((img, idx) => {
    if (!img.bbox || img.bbox.length < 4) {
      return;
    }

    const imagePage =
      img.page ?? (img.position_hint ? Math.floor(img.position_hint) : undefined);
    if (typeof imagePage !== 'number' || !textBBoxesByPage[imagePage]) {
      return;
    }

    if (!shouldIncludeImage(img.bbox, textBBoxesByPage[imagePage], hasCaptions)) {
      return;
    }

    // Filter out images that are not on the current, previous, or following pages relative to the result anchor
    if (result.page_num && result.page_num > 0 && Math.abs(imagePage - result.page_num) > 1) {
      return;
    }

    const imgWidth = img.bbox[2] - img.bbox[0];
    const imgHeight = img.bbox[3] - img.bbox[1];
    if (imgWidth * imgHeight < MIN_IMAGE_AREA) {
      return;
    }

    orderedElements.push({
      element_type: 'image',
      path: img.path,
      page: img.page || (img.position_hint ? Math.floor(img.position_hint) : 0),
      position_hint: img.position_hint || 0,
      key: `element-image-${idx}`
    });
  });
};

const addLegacyTableElements = (
  result: SearchResult,
  orderedElements: Array<ChunkElement & { key: string }>
) => {
  if (!result.elements || result.elements.length === 0) {
    return;
  }

  const textBBoxesByPage = collectTextBBoxesByPage(result.elements);
  const hasCaptions = hasCaptionKeywords(result.elements);

  const tablesToCheck = result.tables || (result.table_data ? [result.table_data] : []);
  tablesToCheck.forEach((table, idx) => {
    if (!table.image_path) {
      return;
    }

    if (
      !table.bbox ||
      table.bbox.length < 4 ||
      typeof table.page !== 'number' ||
      !textBBoxesByPage[table.page] ||
      !shouldIncludeImage(table.bbox, textBBoxesByPage[table.page], hasCaptions)
    ) {
      return;
    }

    // Filter out tables that are not on the current, previous, or following pages relative to the result anchor
    if (result.page_num && result.page_num > 0 && Math.abs(table.page - result.page_num) > 1) {
      return;
    }

    orderedElements.push({
      element_type: 'table',
      path: table.image_path,
      page: table.page || result.page_num || 0,
      position_hint: table.position_hint || 0,
      key: `element-table-${idx}`
    });
  });
};

const sortOrderedElements = (elements: Array<ChunkElement & { key: string }>) =>
  elements.sort((a, b) => {
    if (a.page !== b.page) {
      return a.page - b.page;
    }
    return a.position_hint - b.position_hint;
  });

export const buildOrderedElements = (result: SearchResult) => {
  const orderedElements: Array<ChunkElement & { key: string }> = [];
  if (result.chunk_elements && result.chunk_elements.length > 0) {
    addChunkElements(result, orderedElements);
    return orderedElements;
  }

  addLegacyTextElements(result, orderedElements);
  addLegacyImageElements(result, orderedElements);
  addLegacyTableElements(result, orderedElements);
  return sortOrderedElements(orderedElements);
};
