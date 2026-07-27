import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';

interface DocumentTitleSelectProps {
  dataSource: string;
  value: string[];
  onChange: (titles: string[]) => void;
}

interface DocumentsResponse {
  documents?: Array<{ title?: string }>;
}

const SEARCH_DEBOUNCE_MS = 300;
const MIN_TERM_LENGTH = 2;

/**
 * Typeahead multiselect for restricting a test case to specific documents.
 *
 * Suggestions come from the admin ``/documents`` listing (indexed docs for the
 * dataset's data source), so only real, exact display titles can be selected —
 * these resolve to doc_ids at run time on the backend. Selected titles are shown
 * as removable chips and surfaced to the parent as ``doc_titles``.
 */
const DocumentTitleSelect: React.FC<DocumentTitleSelectProps> = ({
  dataSource,
  value,
  onChange,
}) => {
  const [term, setTerm] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const query = term.trim();
    if (!dataSource || query.length < MIN_TERM_LENGTH) {
      setSuggestions([]);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    const handle = window.setTimeout(async () => {
      try {
        const resp = await axios.get<DocumentsResponse>(`${API_BASE_URL}/documents`, {
          params: {
            data_source: dataSource,
            title: query,
            status: 'indexed',
            page_size: 20,
          },
        });
        if (cancelled) return;
        const titles = (resp.data.documents || [])
          .map((doc) => doc.title)
          .filter((t): t is string => Boolean(t));
        setSuggestions(Array.from(new Set(titles)));
      } catch {
        if (!cancelled) setSuggestions([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [term, dataSource]);

  const addTitle = (title: string) => {
    if (!value.includes(title)) onChange([...value, title]);
    setTerm('');
    setSuggestions([]);
  };

  const removeTitle = (title: string) => {
    onChange(value.filter((t) => t !== title));
  };

  const available = suggestions.filter((t) => !value.includes(t));

  return (
    <div className="testing-doc-select">
      {value.length > 0 && (
        <div className="testing-case-tags" style={{ marginBottom: '0.4rem' }}>
          {value.map((title) => (
            <span key={title} className="testing-tag" title={title}>
              {title}
              <button
                type="button"
                className="testing-tag-remove"
                aria-label={`Remove ${title}`}
                onClick={() => removeTitle(title)}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        disabled={!dataSource}
        placeholder={
          dataSource
            ? 'Type to search document titles…'
            : 'No data source for this dataset'
        }
      />
      {loading && <small className="text-muted">Searching…</small>}
      {!loading && available.length > 0 && (
        <ul className="testing-doc-suggestions">
          {available.map((title) => (
            <li key={title}>
              <button
                type="button"
                className="testing-doc-suggestion"
                onClick={() => addTitle(title)}
              >
                {title}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default DocumentTitleSelect;
