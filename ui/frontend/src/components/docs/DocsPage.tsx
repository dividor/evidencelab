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

interface TocHeading {
  id: string;
  text: string;
  level: number;
}

const slugify = (text: string): string =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim();

const DocsPage: React.FC<DocsPageProps> = ({ basePath = '' }) => {
  const [manifest, setManifest] = useState<DocsManifest | null>(null);
  const [activePath, setActivePath] = useState<string>('');
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<DocNode[] | null>(null);
  const [activeHeading, setActiveHeading] = useState<string>('');
  // Use a ref for the cache to avoid triggering re-renders on cache updates
  const docCacheRef = useRef<Map<string, string>>(new Map());
  // Counter to trigger search re-evaluation after cache loads
  const [cacheVersion, setCacheVersion] = useState(0);
  const contentRef = useRef<HTMLDivElement>(null);

  const withBase = useCallback(
    (p: string) => (basePath ? `${basePath}${p}` : p),
    [basePath]
  );

  // Extract headings from markdown content
  const headings = useMemo((): TocHeading[] => {
    if (!content) return [];
    const result: TocHeading[] = [];
    // Track if we're inside a code block
    let inCodeBlock = false;
    for (const line of content.split('\n')) {
      if (line.trimStart().startsWith('```')) {
        inCodeBlock = !inCodeBlock;
        continue;
      }
      if (inCodeBlock) continue;
      const match = line.match(/^(#{2,3})\s+(.+)/);
      if (match) {
        const text = match[2].trim();
        result.push({ id: slugify(text), text, level: match[1].length });
      }
    }
    return result;
  }, [content]);

  // IntersectionObserver to track visible heading
  useEffect(() => {
    if (headings.length < 2) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the topmost visible heading
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveHeading(entry.target.id);
            break;
          }
        }
      },
      { rootMargin: '-80px 0px -70% 0px', threshold: 0 }
    );

    // Small delay to let ReactMarkdown render heading elements
    const timer = setTimeout(() => {
      for (const h of headings) {
        const el = document.getElementById(h.id);
        if (el) observer.observe(el);
      }
    }, 100);

    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [headings]);

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

    // Scroll content to top on navigation
    if (contentRef.current) {
      contentRef.current.scrollTop = 0;
    }

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
    setActiveHeading('');
    const params = new URLSearchParams(window.location.search);
    params.set('tab', 'docs');
    params.set('path', path);
    const newUrl = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState(null, '', newUrl);
  }, []);

  // Custom ReactMarkdown components for heading IDs, image path resolution, and doc links
  const markdownComponents = useMemo(
    () => ({
      h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => {
        const text = String(children);
        const id = slugify(text);
        return <h2 id={id} {...props}>{children}</h2>;
      },
      h3: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => {
        const text = String(children);
        const id = slugify(text);
        return <h3 id={id} {...props}>{children}</h3>;
      },
      img: ({ src, alt, ...props }: React.ImgHTMLAttributes<HTMLImageElement>) => {
        const resolved = src?.startsWith('/docs/') ? withBase(src) : src;
        return <img src={resolved} alt={alt || ''} {...props} />;
      },
      a: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
        // Intercept links to other docs pages (e.g. /docs/using-evidence-lab/search.md)
        if (href?.startsWith('/docs/') && href.endsWith('.md')) {
          const docPath = href.replace(/^\/docs\//, '');
          return (
            <a
              href="#"
              onClick={(e) => { e.preventDefault(); handleNavigate(docPath); }}
              {...props}
            >
              {children}
            </a>
          );
        }
        // External links open in new tab
        if (href?.startsWith('http')) {
          return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
        }
        return <a href={href} {...props}>{children}</a>;
      },
    }),
    [withBase, handleNavigate]
  );

  const handleTocClick = useCallback((id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
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
        <div className="docs-content" ref={contentRef}>
          <div className="about-content">
            {loading ? (
              <p>Loading...</p>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {content}
              </ReactMarkdown>
            )}
          </div>
        </div>
        {headings.length >= 2 && !loading && (
          <nav className="docs-toc">
            <div className="docs-toc-title">On this page</div>
            {headings.map((h) => (
              <button
                key={h.id}
                className={`docs-toc-item${h.level === 3 ? ' docs-toc-indent' : ''}${activeHeading === h.id ? ' active' : ''}`}
                onClick={() => handleTocClick(h.id)}
              >
                {h.text}
              </button>
            ))}
          </nav>
        )}
      </div>
    </div>
  );
};

export default DocsPage;
