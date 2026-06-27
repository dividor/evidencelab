import React, { useCallback } from 'react';
import API_BASE_URL from '../../config';
import { SummaryModelConfig } from '../../types/api';
import { BriefDocument } from './BriefDocument';
import { BriefHistoryModal } from './BriefHistoryModal';
import { BriefOutlineRail } from './BriefOutlineRail';
import { BriefSeed } from './BriefSeed';
import { useBrief } from './useBrief';
import './brief.css';

interface BriefTabProps {
  dataSource: string;
  // The configured chat / deep-research model, used for outline + section research.
  assistantModelConfig?: SummaryModelConfig | null;
}

// Build a portable Markdown rendering of the current brief for export/download.
const briefToMarkdown = (brief: ReturnType<typeof useBrief>): string => {
  const lines: string[] = [`# ${brief.briefTitle}`, ''];
  brief.sections.forEach((s, i) => {
    const hashes = s.level === 2 ? '###' : '##';
    lines.push(`${hashes} ${brief.numbers[i]}. ${s.title}`, '');
    if (s.content) lines.push(s.content, '');
  });
  if (brief.references.length) {
    lines.push('## Footnotes', '');
    brief.references.forEach((r) => {
      const pageSuffix = r.page ? ` (p. ${r.page})` : '';
      lines.push(`${r.n}. ${r.title}${pageSuffix}. _${r.section}_`);
    });
  }
  return lines.join('\n');
};

export const BriefTab: React.FC<BriefTabProps> = ({ dataSource, assistantModelConfig }) => {
  const brief = useBrief({ apiBaseUrl: API_BASE_URL, dataSource, assistantModelConfig });

  const handleExport = useCallback(() => {
    const md = briefToMarkdown(brief);
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const slug = brief.briefTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    a.href = url;
    a.download = `${slug || 'evidence-brief'}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [brief]);

  return (
    <div className="brief-tab">
      {brief.stage === 'seed' ? (
        <BriefSeed brief={brief} />
      ) : (
        <>
          <div className="brief-toolbar">
            <button className="brief-link-btn" onClick={brief.reset}>
              <span className="brief-icon">＋</span> New brief
            </button>
            <button
              className="brief-link-btn"
              onClick={() => brief.setHistoryOpen(true)}
              disabled={brief.history.length === 0}
            >
              <span className="brief-icon">⟲</span> Saved briefs
              {brief.history.length > 0 && (
                <span className="brief-count-badge">{brief.history.length}</span>
              )}
            </button>
          </div>
          {brief.error && <div className="brief-error brief-error-banner">{brief.error}</div>}
          <div className="brief-builder">
            <BriefOutlineRail brief={brief} onExport={handleExport} />
            <BriefDocument brief={brief} />
          </div>
        </>
      )}
      <BriefHistoryModal brief={brief} />
    </div>
  );
};
