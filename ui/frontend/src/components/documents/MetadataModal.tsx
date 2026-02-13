import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  buildMetadataSections,
  buildSummaryDisplayText,
  buildTimelineStages,
  formatTimestamp,
} from './documentsModalUtils';

const MARKDOWN_MARGIN = '0 0 0.5em 0';

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
  indent: number;
};

const TOC_LINE_PATTERN =
  /^\s*\[H(\d)\]\s*(.+?)(?:\s*\|\s*([a-z_]+)\s*)?(?:\s*\|\s*page\s*(\d+)(?:\s*\(([^)]+)\))?\s*(\[Front\])?)?$/;

const renderValueParts = (valueStr: string) => {
  const urlSplitRegex = /(https?:\/\/[^\s]+)/g;
  const urlMatchRegex = /^https?:\/\/[^\s]+$/;
  const parts = valueStr.split(urlSplitRegex);
  return parts.map((part, index) => {
    if (urlMatchRegex.test(part)) {
      return (
        <a
          key={`${part}-${index}`}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="metadata-link"
        >
          {part}
        </a>
      );
    }
    return part || null;
  });
};

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
    indent,
  };
};

const renderStagesValue = (value: unknown) => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const stages = buildTimelineStages(value);
  return (
    <div className="timeline-container metadata-timeline">
      {stages.map((stageInfo, index) => (
        <TimelineStageItem
          key={stageInfo.stageName}
          stageInfo={stageInfo}
          isLast={index === stages.length - 1}
        />
      ))}
    </div>
  );
};

const renderToggleLink = (
  isExpanded: boolean,
  onToggle: () => void,
) => (
  <a
    className="see-more-link"
    href="#"
    onClick={(event) => {
      event.preventDefault();
      onToggle();
    }}
  >
    {isExpanded ? 'See less' : 'See more'}
  </a>
);

const renderSummarySection = (
  item: { key: string; displayKey: string; value: unknown },
  isExpanded: boolean,
  onToggle: () => void,
) => {
  if (item.displayKey !== 'full_summary' || !item.value) {
    return null;
  }
  const summaryText = buildSummaryDisplayText(String(item.value));
  const displayText = isExpanded ? summaryText : '';
  return (
    <div className="markdown-content">
      <ReactMarkdown
        components={{
          p: ({ node, ...props }) => <p style={{ margin: MARKDOWN_MARGIN }} {...props} />,
          ul: ({ node, ...props }) => <ul style={{ margin: MARKDOWN_MARGIN, paddingLeft: '1.5em' }} {...props} />,
          ol: ({ node, ...props }) => <ol style={{ margin: MARKDOWN_MARGIN, paddingLeft: '1.5em' }} {...props} />,
          li: ({ node, ...props }) => <li style={{ margin: '0.2em 0' }} {...props} />,
          h1: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.4em 0 0.2em' }} {...props} />,
          h2: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.4em 0 0.2em' }} {...props} />,
          h3: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.3em 0 0.2em' }} {...props} />,
          h4: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.3em 0 0.2em' }} {...props} />,
          h5: ({ node, ...props }) => <strong {...props} />,
          h6: ({ node, ...props }) => <strong {...props} />,
        }}
      >
        {displayText}
      </ReactMarkdown>
      {summaryText.length > 0 && renderToggleLink(isExpanded, onToggle)}
    </div>
  );
};

const renderTocSection = (
  item: { key: string; displayKey: string; value: unknown },
  isExpanded: boolean,
  onToggle: () => void,
) => {
  if (
    (item.displayKey !== 'toc' && item.displayKey !== 'toc_classified') ||
    !item.value
  ) {
    return null;
  }
  const tocLines = String(item.value)
    .split('\n')
    .filter((line) => line.trim().length > 0);
  const visibleLines = isExpanded ? tocLines : [];
  return (
    <div className="toc-content">
      {visibleLines.map((line, index) => {
        const renderInfo = buildTocRenderInfo(line);
        if (renderInfo) {
          return (
            <div
              key={`${item.key}-${index}`}
              className={`toc-item toc-level-${renderInfo.level}`}
              style={{ paddingLeft: `${renderInfo.indent}px` }}
            >
              {renderInfo.title}
            </div>
          );
        }
        return (
          <div key={`${item.key}-${index}`} className="toc-item">
            {line}
          </div>
        );
      })}
      {tocLines.length > 0 && renderToggleLink(isExpanded, onToggle)}
    </div>
  );
};

const renderLongTextSection = (
  item: { key: string; displayKey: string; value: unknown },
  isExpanded: boolean,
  onToggle: () => void,
) => {
  if (typeof item.value !== 'string' || item.value.length <= 200) {
    return null;
  }
  const displayValue = isExpanded ? item.value : `${item.value.substring(0, 200)}...`;
  return (
    <span>
      {renderValueParts(displayValue)} {renderToggleLink(isExpanded, onToggle)}
    </span>
  );
};

interface MetadataModalProps {
  isOpen: boolean;
  onClose: () => void;
  metadataDoc: any;
}

export const MetadataModal: React.FC<MetadataModalProps> = ({
  isOpen,
  onClose,
  metadataDoc,
}) => {
  const [expandedKeys, setExpandedKeys] = useState<Record<string, boolean>>({});
  const toggleExpanded = (key: string) => {
    setExpandedKeys((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  if (!isOpen || !metadataDoc) {
    return null;
  }

  const sections = buildMetadataSections(metadataDoc);
  const renderTaxonomies = (value: any, isExpanded: boolean, onToggle: () => void) => {
    if (!value || typeof value !== 'object') {
      return null;
    }

    const allTags: { label: string; reason?: string }[] = [];
    Object.entries(value).forEach(([taxName, tags]) => {
      if (Array.isArray(tags)) {
        tags.forEach(tag => {
          if (typeof tag === 'object' && tag !== null) {
            const code = tag.code || '';
            const name = tag.name || '';
            const label = name ? `${code} - ${name}` : code;
            allTags.push({ label, reason: tag.reason });
          } else {
            allTags.push({ label: String(tag) });
          }
        });
      }
    });

    if (allTags.length === 0) return <span>-</span>;

    const visibleTags = isExpanded ? allTags : allTags.slice(0, 3);
    const hasMore = allTags.length > 3;

    return (
      <div className="taxonomy-list">
        {visibleTags.map((tag, idx) => (
          <div key={idx} className="taxonomy-item" style={{ marginBottom: '4px' }}>
            <span>{tag.label}</span>
            {tag.reason && isExpanded && (
              <div style={{ fontSize: '0.85em', color: '#666', marginLeft: '8px' }}>
                {tag.reason}
              </div>
            )}
          </div>
        ))}
        {hasMore && renderToggleLink(isExpanded, onToggle)}
      </div>
    );
  };

  const renderValue = (item: { key: string; displayKey: string; value: any }) => {
    const isExpanded = expandedKeys[item.key] === true;
    const toggle = () => toggleExpanded(item.key);

    if (item.key === 'sys_taxonomies') {
      return renderTaxonomies(item.value, isExpanded, toggle);
    }

    if (item.key === 'sys_stages') {
      const stagesValue = renderStagesValue(item.value);
      if (stagesValue) {
        return stagesValue;
      }
    }

    const summarySection = renderSummarySection(item, isExpanded, toggle);
    if (summarySection) {
      return summarySection;
    }

    const tocSection = renderTocSection(item, isExpanded, toggle);
    if (tocSection) {
      return tocSection;
    }

    const longTextSection = renderLongTextSection(item, isExpanded, toggle);
    if (longTextSection) {
      return longTextSection;
    }

    if (item.value === null || item.value === undefined) {
      return '-';
    }

    if (typeof item.value === 'object' && item.value !== null && !Array.isArray(item.value)) {
      return (
        <pre className="json-value" style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: '0.85em' }}>
          {JSON.stringify(item.value, null, 2)}
        </pre>
      );
    }

    const valueStr = Array.isArray(item.value)
      ? item.value.map(v => (typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v))).join(', ')
      : String(item.value);
    return renderValueParts(valueStr);
  };

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>Document Metadata</h2>
          <button onClick={onClose} className="modal-close">
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="metadata-content">
            <table className="metadata-table">
              <tbody>
                {sections.map((section, index) => (
                  <React.Fragment key={section.label}>
                    {section.items.length > 0 && (
                      <tr className="metadata-section">
                        <td className="metadata-key" colSpan={2}>
                          <strong>{section.label}</strong>
                        </td>
                      </tr>
                    )}
                    {section.items.map((item) => (
                      <tr key={item.key}>
                        <td className="metadata-key">{item.displayKey}</td>
                        <td className="metadata-value">{renderValue(item)}</td>
                      </tr>
                    ))}
                    {section.items.length > 0 &&
                      sections.slice(index + 1).some((next) => next.items.length > 0) && (
                        <tr className="metadata-divider">
                          <td colSpan={2}>
                            <div className="metadata-divider-line" />
                          </td>
                        </tr>
                      )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

const TimelineStageItem: React.FC<{
  stageInfo: ReturnType<typeof buildTimelineStages>[number];
  isLast: boolean;
}> = ({ stageInfo, isLast }) => (
  <div
    className={`timeline-item ${stageInfo.isSuccess ? 'success' : ''} ${stageInfo.isFailed ? 'failed' : ''
      } ${stageInfo.isPending ? 'pending' : ''}`}
  >
    <div className="timeline-marker">
      {stageInfo.isSuccess && <span className="marker-icon success">✓</span>}
      {stageInfo.isFailed && <span className="marker-icon failed">✗</span>}
      {stageInfo.isPending && <span className="marker-icon pending">○</span>}
    </div>
    <div className="timeline-content">
      <div className="timeline-label">
        {stageInfo.label}
        {stageInfo.stage?.elapsed_seconds !== undefined && (
          <span className="timeline-elapsed">{stageInfo.stage.elapsed_seconds}s</span>
        )}
      </div>
      {stageInfo.stage && (
        <>
          <div className="timeline-timestamp">{formatTimestamp(stageInfo.stage.at)}</div>
          {stageInfo.stage.error && <div className="timeline-error">{stageInfo.stage.error}</div>}
          {stageInfo.stage.page_count !== undefined && (
            <div className="timeline-meta">
              {stageInfo.stage.page_count} pages, {stageInfo.stage.word_count || 0} words
            </div>
          )}
          {stageInfo.stage.method && (
            <div className="timeline-meta">Method: {stageInfo.stage.method}</div>
          )}
          {stageInfo.stage.sections_count !== undefined && (
            <div className="timeline-meta">{stageInfo.stage.sections_count} sections</div>
          )}
          {stageInfo.stage.chunks_count !== undefined && (
            <div className="timeline-meta">{stageInfo.stage.chunks_count} chunks</div>
          )}
        </>
      )}
    </div>
    {!isLast && (
      <div className={`timeline-connector ${stageInfo.isSuccess ? 'completed' : ''}`}></div>
    )}
  </div>
);
