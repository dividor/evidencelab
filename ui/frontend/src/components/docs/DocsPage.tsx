import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import DocsSidebar from './DocsSidebar';

export interface DocNode {
  title: string;
  path: string;
}

export interface DocFolder {
  title: string;
  children: DocNode[];
}

interface DocsManifest {
  title: string;
  tree: DocFolder[];
}

interface DocsPageProps {
  basePath?: string;
}

const DocsPage: React.FC<DocsPageProps> = ({ basePath = '' }) => {
  const [manifest, setManifest] = useState<DocsManifest | null>(null);
  const [activePath, setActivePath] = useState<string>('');
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<DocNode[] | null>(null);
  // Use a ref for the cache to avoid triggering re-renders on cache updates
  const docCacheRef = useRef<Map<string, string>>(new Map());
  // Counter to trigger search re-evaluation after cache loads
  const [cacheVersion, setCacheVersion] = useState(0);

  const withBase = useCallback(
    (p: string) => (basePath ? `${basePath}${p}` : p),
    [basePath]
  );

  // Load manifest on mount
  useEffect(() => {
    fetch(`${withBase('/docs/docs.json')}?t=${Date.now()}`)
      .then((r) => r.json())
      .then((data: DocsManifest) => {
        setManifest(data);
        const params = new URLSearchParams(window.location.search);
        const urlPath = params.get('path');
        const firstDoc = data.tree[0]?.children[0]?.path;
        setActivePath(urlPath || firstDoc || '');
      })
      .catch((err) => console.error('Failed to load docs manifest:', err));
  }, [withBase]);

  // Load doc content when active path changes
  useEffect(() => {
    if (!activePath) return;

    const cached = docCacheRef.current.get(activePath);
    if (cached !== undefined) {
      setContent(cached);
      return;
    }

    setLoading(true);
    const docUrl = withBase('/docs/' + activePath);
    fetch(`${docUrl}?t=${Date.now()}`)
      .then((r) => r.text())
      .then((text) => {
        setContent(text);
        docCacheRef.current.set(activePath, text);
      })
      .catch((err) => {
        console.error('Failed to load doc:', err);
        setContent('# Not Found\n\nThis document could not be loaded.');
      })
      .finally(() => setLoading(false));
  }, [activePath, withBase]);

  // All doc nodes flattened
  const allDocs = useMemo(() => {
    if (!manifest) return [];
    return manifest.tree.flatMap((folder) => folder.children);
  }, [manifest]);

  // Search: filter by title and cached content
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }

    const query = searchQuery.toLowerCase();
    const cache = docCacheRef.current;

    const titleMatches = allDocs.filter((doc) =>
      doc.title.toLowerCase().includes(query)
    );

    const titleMatchPaths = new Set(titleMatches.map((d) => d.path));
    const contentMatches = allDocs.filter((doc) => {
      if (titleMatchPaths.has(doc.path)) return false;
      const cached = cache.get(doc.path);
      return cached !== undefined && cached.toLowerCase().includes(query);
    });

    setSearchResults([...titleMatches, ...contentMatches]);

    // Pre-fetch uncached docs so content search works on next keystroke
    const uncached = allDocs.filter((doc) => !cache.has(doc.path));
    if (uncached.length > 0) {
      Promise.all(
        uncached.map((doc) => {
          const url = withBase('/docs/' + doc.path);
          return fetch(`${url}?t=${Date.now()}`)
            .then((r) => r.text())
            .then((text) => ({ path: doc.path, text }))
            .catch(() => ({ path: doc.path, text: '' }));
        }
        )
      ).then((results) => {
        for (const r of results) {
          cache.set(r.path, r.text);
        }
        setCacheVersion((v) => v + 1);
      });
    }
  }, [searchQuery, allDocs, withBase, cacheVersion]);

  const handleNavigate = useCallback((path: string) => {
    setActivePath(path);
    const params = new URLSearchParams(window.location.search);
    params.set('tab', 'docs');
    params.set('path', path);
    const newUrl = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState(null, '', newUrl);
  }, []);

  if (!manifest) {
    return (
      <div className="main-content">
        <div className="docs-page">
          <div className="docs-loading">Loading documentation...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="main-content">
      <div className="docs-page">
        <DocsSidebar
          tree={manifest.tree}
          activePath={activePath}
          searchQuery={searchQuery}
          searchResults={searchResults}
          onNavigate={handleNavigate}
          onSearchChange={setSearchQuery}
        />
        <div className="docs-content">
          <div className="about-content">
            {loading ? (
              <p>Loading...</p>
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default DocsPage;
