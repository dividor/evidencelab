/**
 * Attach each cited document's publication year to a brief's export results.
 *
 * Brief citations carry a document's title, page and links but not its year,
 * which lives on the documents table. The Word export shows the year in its
 * References list (as the search export does), so before the document is built
 * the export looks the year up once per cited document through the document
 * metadata endpoint. The year is decoration on the reference, so a document
 * whose lookup fails (for example one no longer in the library) is exported
 * without a year and the failure is logged, rather than blocking the export.
 */
import axios from 'axios';
import API_BASE_URL from '../config';
import type { SearchResult } from '../types/api';

const yearOf = (payload: unknown): string => {
  const raw = (payload as { published_year?: string | number | null } | null)?.published_year;
  return raw === undefined || raw === null ? '' : String(raw).trim();
};

const fetchDocumentYear = async (docId: string, dataSource: string): Promise<string> => {
  try {
    const response = await axios.get(`${API_BASE_URL}/document/${encodeURIComponent(docId)}`, {
      params: { data_source: dataSource },
    });
    return yearOf(response.data);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    console.warn(`Brief export: no publication year for cited document ${docId}: ${detail}`);
    return '';
  }
};

/** Return a copy of `results` with `year` set from each document's metadata.
 *  Each distinct `doc_id` is fetched once; a document without a recorded year,
 *  or whose lookup fails, leaves its results unchanged. */
export const withDocumentYears = async (
  results: SearchResult[],
  dataSource: string,
): Promise<SearchResult[]> => {
  const docIds = Array.from(new Set(results.map((r) => r.doc_id).filter(Boolean)));
  const years = new Map<string, string>();
  await Promise.all(
    docIds.map(async (docId) => {
      const year = await fetchDocumentYear(docId, dataSource);
      if (year) years.set(docId, year);
    }),
  );
  return results.map((r) => {
    const year = years.get(r.doc_id);
    return year ? { ...r, year } : r;
  });
};
