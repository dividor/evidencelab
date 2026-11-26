import React, { useEffect, useState } from 'react';
import { DocsSection } from '../../utils/docsLocation';
import { DocFolder, DocNode } from './useDocsContent';

interface DocsSidebarProps {
  section: DocsSection;
  tree: DocFolder[];
  activePath: string;
  searchQuery: string;
  searchResults: DocNode[] | null;
  searchStatus?: string;
  onNavigate: (path: string) => void;
  onSearchChange: (query: string) => void;
}

const DocsSidebar = ({
  section,
  tree,
  activePath,
  searchQuery,
  searchResults,
  searchStatus,
  onNavigate,
  onSearchChange,
}: DocsSidebarProps) => {
  const [expandedFolders, setExpandedFolders] = useState(new Set(['Using Evidence Lab']));
  const activeFolder = tree.find((folder) => folder.children.some((doc) => doc.path === activePath));
  const searchLabel = section === 'admin' ? 'Search admin docs' : 'Search docs';

  useEffect(() => {
    if (activeFolder) setExpandedFolders((prev) => new Set(prev).add(activeFolder.title));
  }, [activeFolder]);

  const toggleFolder = (title: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(title)) next.delete(title);
      else next.add(title);
      return next;
    });
  };

  const renderArticle = (doc: DocNode) => (
    <button
      type="button"
      key={doc.path}
      className={`docs-nav-item${doc.path === activePath ? ' active' : ''}`}
      aria-current={doc.path === activePath ? 'page' : undefined}
      onClick={() => onNavigate(doc.path)}
    >
      {doc.title}
    </button>
  );

  return (
    <div className="docs-sidebar">
      <div className="docs-search">
        <input
          type="search"
          aria-label={searchLabel}
          placeholder={`${searchLabel}…`}
          value={searchQuery}
          onChange={(event) => onSearchChange(event.target.value)}
          className="docs-search-input"
        />
      </div>
      <nav className="docs-nav-tree" aria-label={section === 'admin' ? 'Admin articles' : 'Docs articles'}>
        {searchResults ? (
          <>
            {searchResults.map(renderArticle)}
            {searchStatus && <div className="docs-no-results" role="status">{searchStatus}</div>}
            {!searchStatus && searchResults.length === 0 && (
              <div className="docs-no-results" role="status">No results found</div>
            )}
          </>
        ) : tree.map((folder) => {
          const isExpanded = expandedFolders.has(folder.title);
          return (
            <div key={folder.title} className="docs-nav-folder">
              <button
                type="button"
                className="docs-nav-folder-header"
                aria-expanded={isExpanded}
                onClick={() => toggleFolder(folder.title)}
              >
                <span className="docs-nav-folder-arrow" aria-hidden="true">
                  {isExpanded ? '▾' : '▸'}
                </span>
                {folder.title}
              </button>
              {isExpanded && (
                <div className="docs-nav-folder-children">
                  {folder.children.map(renderArticle)}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </div>
  );
};

export default DocsSidebar;
