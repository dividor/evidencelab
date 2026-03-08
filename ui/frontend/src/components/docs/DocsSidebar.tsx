import React, { useState, useEffect } from 'react';
import { DocFolder, DocNode } from './DocsPage';

interface DocsSidebarProps {
  tree: DocFolder[];
  activePath: string;
  searchQuery: string;
  searchResults: DocNode[] | null;
  onNavigate: (path: string) => void;
  onSearchChange: (query: string) => void;
}

const DocsSidebar: React.FC<DocsSidebarProps> = ({
  tree,
  activePath,
  searchQuery,
  searchResults,
  onNavigate,
  onSearchChange,
}) => {
  // Track which folders are expanded
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(
    new Set()
  );

  // Auto-expand folder containing the active page
  useEffect(() => {
    if (!activePath) return;
    for (const folder of tree) {
      if (folder.children.some((child) => child.path === activePath)) {
        setExpandedFolders((prev) => {
          const next = new Set(prev);
          next.add(folder.title);
          return next;
        });
        break;
      }
    }
  }, [activePath, tree]);

  const toggleFolder = (title: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(title)) {
        next.delete(title);
      } else {
        next.add(title);
      }
      return next;
    });
  };

  // When searching, show flat results list
  if (searchQuery.trim() && searchResults) {
    return (
      <div className="docs-sidebar">
        <div className="docs-search">
          <input
            type="text"
            placeholder="Search docs..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="docs-search-input"
          />
        </div>
        <nav className="docs-nav-tree">
          {searchResults.length === 0 ? (
            <div className="docs-no-results">No results found</div>
          ) : (
            searchResults.map((doc) => (
              <button
                key={doc.path}
                className={`docs-nav-item${doc.path === activePath ? ' active' : ''}`}
                onClick={() => onNavigate(doc.path)}
              >
                {doc.title}
              </button>
            ))
          )}
        </nav>
      </div>
    );
  }

  return (
    <div className="docs-sidebar">
      <div className="docs-search">
        <input
          type="text"
          placeholder="Search docs..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="docs-search-input"
        />
      </div>
      <nav className="docs-nav-tree">
        {tree.map((folder) => {
          const isExpanded = expandedFolders.has(folder.title);
          return (
            <div key={folder.title} className="docs-nav-folder">
              <button
                className={`docs-nav-folder-header${isExpanded ? ' expanded' : ''}`}
                onClick={() => toggleFolder(folder.title)}
              >
                <span className="docs-nav-folder-arrow">
                  {isExpanded ? '▾' : '▸'}
                </span>
                {folder.title}
              </button>
              {isExpanded && (
                <div className="docs-nav-folder-children">
                  {folder.children.map((doc) => (
                    <button
                      key={doc.path}
                      className={`docs-nav-item${doc.path === activePath ? ' active' : ''}`}
                      onClick={() => onNavigate(doc.path)}
                    >
                      {doc.title}
                    </button>
                  ))}
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
