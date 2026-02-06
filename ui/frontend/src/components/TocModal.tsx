import React, { useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';

type ParsedTocLine = {
  level: string;
  title: string;
  category?: string;
  page?: string;
  roman?: string;
  front?: string;
};

type TocRenderInfo = {
  level: number;
  title: string;
  sectionType: string;
  page?: string;
  roman?: string;
  front?: string;
  indent: number;
  isBeforeFrontMatterBoundary: boolean;
};

const TOC_LINE_PATTERN =
  /^\s*\[H(\d)\]\s*(.+?)(?:\s*\|\s*([a-z_]+)\s*)?(?:\s*\|\s*page\s*(\d+)(?:\s*\(([^)]+)\))?\s*(\[Front\])?)?$/;
const FRONT_MATTER_PATTERN = /\|\s*page\s*(\d+)(?:\s*\([^)]+\))?\s*(\[Front\])?\s*$/i;

const parseTocLine = (line: string): ParsedTocLine | null => {
  const match = line.match(TOC_LINE_PATTERN);
  if (!match) {
    return null;
  }
  return {
    level: match[1],
    title: match[2].trim(),
    category: match[3],
    page: match[4],
    roman: match[5],
    front: match[6],
  };
};

const formatTocLine = (parsed: ParsedTocLine, category: string): string => {
  const romanSuffix = parsed.roman ? ` (${parsed.roman})` : '';
  const fmSuffix = parsed.front ? ' [Front]' : '';
  const pageSuffix = parsed.page ? ` | page ${parsed.page}${romanSuffix}${fmSuffix}` : '';
  return `[H${parsed.level}] ${parsed.title} | ${category}${pageSuffix}`;
};

const updateTocLineCategory = (lines: string[], lineIndex: number, category: string) => {
  const parsed = parseTocLine(lines[lineIndex]);
  if (!parsed) {
    return;
  }
  lines[lineIndex] = formatTocLine(parsed, category);
};

const getFrontMatterBoundary = (tocText: string | null): number | null => {
  if (!tocText) return null;
  let maxPage: number | null = null;
  for (const line of tocText.split('\n')) {
    const match = line.match(FRONT_MATTER_PATTERN);
    if (!match || !match[2]) {
      continue;
    }
    const page = parseInt(match[1], 10);
    if (!Number.isNaN(page) && (maxPage === null || page > maxPage)) {
      maxPage = page;
    }
  }
  return maxPage;
};

const buildTocRenderInfo = (line: string): TocRenderInfo | null => {
  const parsed = parseTocLine(line);
  if (!parsed) {
    return null;
  }
  const level = Math.min(Math.max(parseInt(parsed.level, 10), 1), 6);
  const indent = Math.max(level - 1, 0) * 20;
  return {
    level,
    title: parsed.title,
    sectionType: parsed.category || 'other',
    page: parsed.page,
    roman: parsed.roman,
    front: parsed.front,
    indent,
    isBeforeFrontMatterBoundary: Boolean(parsed.front),
  };
};

const renderPageElement = (
  info: TocRenderInfo,
  onPageSelect: ((page: number) => void) | undefined,
  resolvedPdfUrl: string
) => {
  if (!info.page) {
    return null;
  }
  const pageValue = info.page;
  const romanSuffix = info.roman ? ' (' + info.roman + ')' : '';
  const frontSuffix = info.front ? ' [Front]' : '';
  const pageText = 'p. ' + info.page + romanSuffix + frontSuffix;
  if (onPageSelect) {
    return (
      <button
        type="button"
        onClick={() => onPageSelect(parseInt(pageValue, 10))}
        className="toc-page toc-page-link"
      >
        {pageText}
      </button>
    );
  }
  if (resolvedPdfUrl) {
    return (
      <a
        href={`${resolvedPdfUrl}#page=${info.page}`}
        target="_blank"
        rel="noopener noreferrer"
        className="toc-page toc-page-link"
      >
        {pageText}
      </a>
    );
  }
  return <span className="toc-page">{pageText}</span>;
};

interface TocModalProps {
  isOpen: boolean;
  onClose: () => void;
  toc: string;
  docId: string;
  dataSource: string;
  loading: boolean;
  pdfUrl?: string;
  onPageSelect?: (page: number) => void;
  onTocUpdated?: (newToc: string) => void;
  tocApproved?: boolean;
  onTocApprovedChange?: (approved: boolean) => void;
  pageCount?: number | null;
}

const TocModal: React.FC<TocModalProps> = ({
  isOpen,
  onClose,
  toc,
  docId,
  dataSource,
  loading,
  pdfUrl,
  onPageSelect,
  onTocUpdated,
  tocApproved = false,
  onTocApprovedChange,
  pageCount
}) => {
  const [savingIndex, setSavingIndex] = useState<number | null>(null);
  const [reprocessingToc, setReprocessingToc] = useState(false);
  const [reprocessSuccess, setReprocessSuccess] = useState(false);
  const [draggedCategory, setDraggedCategory] = useState<string | null>(null);
  const [dragStartIndex, setDragStartIndex] = useState<number | null>(null);
  const [draggedOverIndices, setDraggedOverIndices] = useState<Set<number>>(new Set());
  const resolvedPdfUrl = pdfUrl || (docId ? `${API_BASE_URL}/pdf/${docId}?data_source=${dataSource}` : '');

  const frontMatterBoundary = getFrontMatterBoundary(toc || null);

  const categories = [
    'front_matter',
    'executive_summary',
    'acronyms',
    'introduction',
    'context',
    'methodology',
    'findings',
    'recommendations',
    'conclusions',
    'annexes',
    'appendix',
    'references',
    'bibliography',
    'other'
  ];

  const handleTocCategoryChange = async (lineIndex: number, newCategory: string) => {
    if (!docId || !toc) return;

    setSavingIndex(lineIndex);
    try {
      // Parse the current TOC and apply the change
      const lines = toc.split('\n');
      updateTocLineCategory(lines, lineIndex, newCategory);

      const updatedToc = lines.join('\n');

      // Send update to backend
      await axios.put(
        `${API_BASE_URL}/document/${docId}/toc`,
        { toc_classified: updatedToc },
        { params: { data_source: dataSource } }
      );

      // Update parent component
      if (onTocUpdated) {
        onTocUpdated(updatedToc);
      }
    } catch (error) {
      console.error('Error saving TOC edit:', error);
      alert('Failed to save TOC change. Please try again.');
    } finally {
      setSavingIndex(null);
    }
  };

  const handleCopyCategory = async (lineIndex: number, direction: 'up' | 'down') => {
    if (!docId || !toc) return;

    const lines = toc.split('\n');
    const currentLine = lines[lineIndex];

    // Get current category
    const currentMatch = currentLine.match(
      /^\s*\[H(\d)\]\s*(.+?)(?:\s*\|\s*([a-z_]+)\s*)?(?:\s*\|\s*page\s*(\d+)(?:\s*\(([^)]+)\))?)?$/
    );
    if (!currentMatch) return;

    const currentCategory = currentMatch[3] || 'other';

    // Find target line (next/previous non-empty line)
    let targetIndex = direction === 'down' ? lineIndex + 1 : lineIndex - 1;

    // Skip empty lines
    while (targetIndex >= 0 && targetIndex < lines.length && !lines[targetIndex].trim()) {
      targetIndex += (direction === 'down' ? 1 : -1);
    }

    if (targetIndex < 0 || targetIndex >= lines.length) return;

    // Apply category to target line
    await handleTocCategoryChange(targetIndex, currentCategory);
  };

  const handleDragStart = (index: number, category: string) => {
    setDraggedCategory(category);
    setDragStartIndex(index);
    setDraggedOverIndices(new Set([index]));
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (dragStartIndex === null) return;

    // Add all indices between dragStartIndex and current index
    const newIndices = new Set<number>();
    const start = Math.min(dragStartIndex, index);
    const end = Math.max(dragStartIndex, index);

    for (let i = start; i <= end; i++) {
      newIndices.add(i);
    }

    setDraggedOverIndices(newIndices);
  };

  const handleDragLeave = () => {
    // Don't clear on drag leave, only on drop or drag end
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();

    if (!draggedCategory || !docId || !toc || savingIndex !== null || draggedOverIndices.size === 0) {
      setDraggedCategory(null);
      setDragStartIndex(null);
      setDraggedOverIndices(new Set());
      return;
    }

    // Apply category to all dragged over items at once
    const indicesToUpdate = Array.from(draggedOverIndices).sort((a, b) => a - b);

    try {
      // Parse the current TOC and apply changes to all selected lines
      const lines = toc.split('\n');
      for (const targetIndex of indicesToUpdate) {
        if (targetIndex !== dragStartIndex && targetIndex < lines.length) {
          updateTocLineCategory(lines, targetIndex, draggedCategory);
        }
      }

      const updatedToc = lines.join('\n');

      // Send single update to backend with all changes
      await axios.put(
        `${API_BASE_URL}/document/${docId}/toc`,
        { toc_classified: updatedToc },
        { params: { data_source: dataSource } }
      );

      // Update parent component
      if (onTocUpdated) {
        onTocUpdated(updatedToc);
      }
    } catch (error) {
      console.error('Error saving TOC drag fill:', error);
      alert('Failed to save TOC changes. Please try again.');
    } finally {
      setDraggedCategory(null);
      setDragStartIndex(null);
      setDraggedOverIndices(new Set());
    }
  };

  const handleDragEnd = () => {
    setDraggedCategory(null);
    setDragStartIndex(null);
    setDraggedOverIndices(new Set());
  };

  const handleReprocessToc = async () => {
    if (!docId) return;

    setReprocessingToc(true);
    try {
      // Set a generous timeout (e.g. 60s) to prevent UI freeze if backend hangs
      const response = await axios.post(
        `${API_BASE_URL}/documents/${docId}/reprocess-toc?data_source=${dataSource}`,
        {},
        { timeout: 60000 }
      );

      const data = response.data as { success?: boolean; toc_classified?: string; message?: string };
      if (data.success) {
        if (data.toc_classified) {
          if (onTocUpdated) {
            onTocUpdated(data.toc_classified);
          }
        } else {
          // Async case
          console.log('Reprocessing started in background.');
          setReprocessSuccess(true);
          // Removed timeout so status "sticks" as requested
        }
      } else {
        console.error('Reprocess failed:', data.message);
      }
    } catch (err) {
      console.error('Error reprocessing TOC:', err);
    } finally {
      setReprocessingToc(false);
    }
  };

  const handleToggleApproved = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked;
    try {
      await axios.patch(
        `${API_BASE_URL}/documents/${docId}`,
        { toc_approved: checked },
        { params: { data_source: dataSource } }
      );
      if (onTocApprovedChange) {
        onTocApprovedChange(checked);
      }
    } catch (err) {
      console.error("Error updating approval status:", err);
      alert("Failed to update approval status");
    }
  };

  const handleClose = () => {
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="preview-overlay" onClick={handleClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="toc-header">
            <h2>Table of Contents</h2>
            {frontMatterBoundary && frontMatterBoundary > 0 ? (
              <span className="toc-boundary-note">
                Front matter boundary: p. {frontMatterBoundary}
              </span>
            ) : null}
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '5px', cursor: 'pointer', userSelect: 'none', marginRight: '10px' }}>
              <input
                type="checkbox"
                checked={tocApproved}
                onChange={handleToggleApproved}
              />
              <span style={{ fontSize: '0.9em', fontWeight: 500 }}>Approved</span>
            </label>

            <button
              onClick={handleReprocessToc}
              disabled={loading || reprocessingToc || reprocessSuccess}
              className="toc-action-btn toc-reprocess-btn"
              title="Reprocess content category classifications using AI"
            >
              {reprocessingToc ? 'Reprocessing...' : reprocessSuccess ? 'Processing...' : 'Reprocess'}
            </button>
            <button onClick={handleClose} className="modal-close">×</button>
          </div>
        </div>
        <div className="modal-body">
          {loading ? (
            <div className="summary-content">Loading table of contents...</div>
          ) : !toc ? (
            <div className="summary-content">No table of contents available for this document.</div>
          ) : (
            <div className="summary-content markdown-content">
              <div className="toc-content">
                {toc.split('\n').map((line, index) => {
                  if (!line.trim()) return null;

                  const renderInfo = buildTocRenderInfo(line);
                  if (renderInfo) {
                    return (
                      <div
                        key={index}
                        className={`toc-item toc-level-${renderInfo.level} ${draggedOverIndices.has(index) ? 'toc-item-drag-over' : ''} ${renderInfo.isBeforeFrontMatterBoundary ? 'toc-item-before-boundary' : ''}`}
                        style={{ paddingLeft: `${renderInfo.indent}px`, display: 'flex', alignItems: 'center', gap: '10px' }}
                        onDragOver={(e) => handleDragOver(e, index)}
                        onDrop={(e) => handleDrop(e)}
                      >
                        <span className="toc-title" style={{ flex: 1 }}>
                          {renderInfo.title}
                        </span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <select
                            value={renderInfo.sectionType}
                            onChange={(e) => handleTocCategoryChange(index, e.target.value)}
                            className={`toc-section-tag toc-section-tag-editable section-tag-${renderInfo.sectionType}`}
                            disabled={savingIndex === index}
                          >
                            {categories.map(cat => (
                              <option key={cat} value={cat}>
                                {cat.replace(/_/g, ' ')}
                              </option>
                            ))}
                          </select>
                          <div
                            className="toc-drag-handle"
                            draggable={savingIndex === null}
                            onDragStart={() => handleDragStart(index, renderInfo.sectionType)}
                            onDragEnd={handleDragEnd}
                            title="Drag down or up to fill multiple items with this category"
                          >
                            ⋮⋮
                          </div>
                        </div>
                        {renderPageElement(renderInfo, onPageSelect, resolvedPdfUrl)}
                      </div>
                    );
                  }
                  // Fallback for non-matching lines
                  return <div key={index} className="toc-item">{line}</div>;
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default TocModal;
