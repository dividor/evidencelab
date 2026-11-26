import React, { useCallback, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import {
  docsArticleUrl,
  docsSectionForPath,
  notifyDocsLocation,
  useDocsLocation,
} from '../../utils/docsLocation';
import DocsArticle from './DocsArticle';
import DocsSidebar from './DocsSidebar';
import { useDocsArticle, useDocsManifest, useDocsReader, useDocsSearch } from './useDocsContent';

interface DocsPageProps {
  basePath?: string;
  initialPath?: string;
}

const DocsPage: React.FC<DocsPageProps> = ({ basePath = '', initialPath }) => {
  const { section, path, anchor } = useDocsLocation(initialPath);
  const { manifest, failed } = useDocsManifest(basePath);
  const [search, setSearch] = useState({ section, query: '' });
  const readDoc = useDocsReader(basePath);

  const tree = useMemo(() => (
    manifest?.tree.map((folder) => ({
      ...folder,
      children: folder.children.filter((doc) => docsSectionForPath(doc.path) === section),
    })).filter((folder) => folder.children.length > 0) ?? []
  ), [manifest, section]);
  const allDocs = useMemo(() => tree.flatMap((folder) => folder.children), [tree]);
  const activePath = path || allDocs[0]?.path || '';
  const article = useDocsArticle(activePath, readDoc);
  const searchQuery = search.section === section ? search.query : '';
  const { results, status } = useDocsSearch(allDocs, searchQuery, readDoc);

  const handleNavigate = useCallback((nextPath: string, nextAnchor = '') => {
    const url = docsArticleUrl(basePath, nextPath, nextAnchor, window.location.search);
    window.history.pushState(null, '', url);
    notifyDocsLocation();
  }, [basePath]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [activePath]);

  useLayoutEffect(() => {
    const header = document.querySelector('.top-bar');
    if (!header) return;

    const rootStyle = document.documentElement.style;
    const updateHeaderHeight = () => {
      rootStyle.setProperty('--docs-header-height', `${header.getBoundingClientRect().height}px`);
    };
    updateHeaderHeight();
    const observer = new ResizeObserver(updateHeaderHeight);
    observer.observe(header);
    return () => {
      observer.disconnect();
      rootStyle.removeProperty('--docs-header-height');
    };
  }, []);

  return (
    <div className="main-content">
      <div className="docs-page">
        {manifest ? (
          <>
            <DocsSidebar
              key={section}
              section={section}
              tree={tree}
              activePath={activePath}
              searchQuery={searchQuery}
              searchResults={results}
              searchStatus={status}
              onNavigate={handleNavigate}
              onSearchChange={(query) => setSearch({ section, query })}
            />
            {article && !article.failed ? (
              <DocsArticle
                key={activePath}
                basePath={basePath}
                path={activePath}
                text={article.text}
                anchor={anchor}
                onNavigate={handleNavigate}
              />
            ) : (
              <div className="docs-content" role="status">
                {article?.failed ? 'This document could not be loaded.' : 'Loading…'}
              </div>
            )}
          </>
        ) : (
          <div className="docs-loading" role="status">
            {failed ? 'Documentation could not be loaded.' : 'Loading documentation...'}
          </div>
        )}
      </div>
    </div>
  );
};

export default DocsPage;
