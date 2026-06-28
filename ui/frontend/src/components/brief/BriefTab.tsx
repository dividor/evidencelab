import { saveAs } from 'file-saver';
import React, { useCallback, useState } from 'react';
import API_BASE_URL, { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import { SearchResult, SourceReference, SummaryModelConfig } from '../../types/api';
import {
  buildExportFilename,
  exportResultsToDocxBlob,
} from '../../utils/exportResultsToDocx';
import { BriefDocument } from './BriefDocument';
import { BriefHistoryModal } from './BriefHistoryModal';
import { BriefOutlineRail } from './BriefOutlineRail';
import { BriefSeed } from './BriefSeed';
import { useBrief } from './useBrief';
import './brief.css';

const CITATION_RE = /\[(\d+(?:,\s*\d+)*)\]/g;

const sourceToResult = (src: SourceReference, dataSource: string): SearchResult => ({
  chunk_id: src.chunkId,
  doc_id: src.docId,
  title: src.title,
  document_title: src.title,
  text: src.text,
  page_num: src.page || 1,
  score: src.score,
  headings: src.headings || [],
  data_source: dataSource,
  metadata: {},
});

/**
 * Flatten the brief into one Markdown body + a global SearchResult[] so it can
 * reuse the search summary's .docx exporter. Each section's per-section citation
 * numbers are remapped to global numbers (deduped by chunk) so `[n]` in the body
 * lines up with the global references list, and citations link to the source
 * document at the cited page.
 */
const assembleBriefForExport = (
  brief: ReturnType<typeof useBrief>,
  dataSource: string,
): { summary: string; results: SearchResult[] } => {
  const results: SearchResult[] = [];
  const keyToGlobal = new Map<string, number>();
  const lines: string[] = [];
  brief.sections.forEach((s, i) => {
    const hashes = s.level === 2 ? '###' : '##';
    lines.push(`${hashes} ${brief.numbers[i]}. ${s.title}`, '');
    if (s.status !== 'done' || !s.content) return;
    const localToGlobal = new Map<number, number>();
    s.sources.forEach((src) => {
      if (src.index == null) return;
      const key = src.chunkId || `${src.docId}:${src.index}`;
      let global = keyToGlobal.get(key);
      if (global == null) {
        results.push(sourceToResult(src, dataSource));
        global = results.length;
        keyToGlobal.set(key, global);
      }
      localToGlobal.set(src.index, global);
    });
    const rewritten = s.content.replace(CITATION_RE, (_m, nums: string) => {
      const mapped = nums
        .split(',')
        .map((x) => localToGlobal.get(parseInt(x.trim(), 10)))
        .filter((g): g is number => g != null);
      return mapped.length ? `[${mapped.join(', ')}]` : '';
    });
    lines.push(rewritten, '');
  });
  return { summary: lines.join('\n'), results };
};

interface BriefTabProps {
  dataSource: string;
  // The configured chat / deep-research model, used for outline + section research.
  assistantModelConfig?: SummaryModelConfig | null;
  // Opens the document preview (citations/footnotes click through to it).
  onResultClick?: (result: SearchResult) => void;
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

export const BriefTab: React.FC<BriefTabProps> = ({
  dataSource,
  assistantModelConfig,
  onResultClick,
}) => {
  const auth = useAuth();
  // Logged-in users get their own saved-briefs bucket; anonymous users share one.
  const userKey = USER_MODULE && auth.user ? String(auth.user.id) : null;
  const brief = useBrief({ apiBaseUrl: API_BASE_URL, dataSource, assistantModelConfig, userKey });
  const [exportBusy, setExportBusy] = useState(false);

  const handleExportWord = useCallback(async () => {
    if (exportBusy) return;
    setExportBusy(true);
    try {
      const { summary, results } = assembleBriefForExport(brief, dataSource);
      const blob = await exportResultsToDocxBlob({
        query: brief.briefTitle || 'Evidence Brief',
        aiSummary: summary,
        results,
        dataSource,
        siteOrigin:
          typeof window !== 'undefined' && window.location ? window.location.origin : undefined,
      });
      saveAs(blob, buildExportFilename(brief.briefTitle || 'evidence-brief', new Date()));
    } catch (err) {
      brief.setError(err instanceof Error ? err.message : 'Export to Word failed');
    } finally {
      setExportBusy(false);
    }
  }, [exportBusy, brief, dataSource]);

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
            <BriefDocument
              brief={brief}
              onResultClick={onResultClick}
              onExportWord={handleExportWord}
              exportBusy={exportBusy}
            />
          </div>
        </>
      )}
      <BriefHistoryModal brief={brief} />
    </div>
  );
};
