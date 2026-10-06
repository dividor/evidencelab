import { useCallback, useRef, useState } from 'react';
import { generateDocumentSummary, saveDocumentSummary, SummaryProgress } from './documentSummaryApi';
import type { SummarySettings } from './summarySettings';
import type { SummaryAdmin } from './useSummaryAdmin';

/** Documents summarised at the same time. */
export const BULK_CONCURRENCY = 2;

export type BulkState = 'waiting' | 'generating' | 'saved' | 'failed' | 'stopped';

export interface BulkItem {
  id: string;
  title: string;
  state: BulkState;
  progress?: SummaryProgress | null;
  message?: string;
}

const failureMessage = (err: unknown): string => {
  const detail = (err as any)?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return err instanceof Error && err.message ? err.message : 'Failed';
};

/**
 * Regenerates and saves the summaries of several documents, a few at a time,
 * from the browser. Each summary is saved as soon as it is ready; a failure
 * is recorded and the rest carry on. Stop aborts the documents in progress
 * and leaves the rest unchanged.
 */
export const useBulkSummaries = (admin: SummaryAdmin | null) => {
  const [items, setItems] = useState<BulkItem[]>([]);
  const [running, setRunning] = useState(false);
  const controllers = useRef(new Map<string, AbortController>());
  const stopped = useRef(false);

  const patch = useCallback((id: string, change: Partial<BulkItem>) => {
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...change } : item)));
  }, []);

  const runOne = useCallback(
    async (doc: { id: string; title: string }, settings: SummarySettings) => {
      if (!admin) return;
      const controller = new AbortController();
      controllers.current.set(doc.id, controller);
      patch(doc.id, { state: 'generating', progress: null });
      try {
        const generated = await generateDocumentSummary({
          dataSource: admin.dataSource,
          docId: doc.id,
          settings,
          model: admin.model,
          onProgress: (progress) => patch(doc.id, { progress }),
          signal: controller.signal,
        });
        const saved = await saveDocumentSummary(admin.dataSource, doc.id, generated.summary, generated.method);
        admin.onSaved(saved);
        patch(doc.id, { state: 'saved', progress: null });
      } catch (err) {
        patch(doc.id, controller.signal.aborted
          ? { state: 'stopped', progress: null }
          : { state: 'failed', progress: null, message: failureMessage(err) });
      } finally {
        controllers.current.delete(doc.id);
      }
    },
    [admin, patch],
  );

  const start = useCallback(
    async (docs: Array<{ id: string; title: string }>, settings: SummarySettings) => {
      stopped.current = false;
      setItems(docs.map((d) => ({ ...d, state: 'waiting' })));
      setRunning(true);
      const queue = [...docs];
      const worker = async () => {
        for (let doc = queue.shift(); doc; doc = queue.shift()) {
          if (stopped.current) {
            patch(doc.id, { state: 'stopped' });
          } else {
            await runOne(doc, settings);
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(BULK_CONCURRENCY, docs.length) }, worker));
      setRunning(false);
    },
    [patch, runOne],
  );

  const stop = useCallback(() => {
    stopped.current = true;
    controllers.current.forEach((controller) => controller.abort());
  }, []);

  const reset = useCallback(() => setItems([]), []);

  return { items, running, start, stop, reset };
};
