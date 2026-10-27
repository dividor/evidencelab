import { useCallback, useState } from 'react';

export interface SelectableDoc {
  doc_id?: string;
  id?: string;
  title?: string;
}

export const docKey = (doc: SelectableDoc): string => String(doc.doc_id || doc.id || '');

/** Documents ticked for a bulk action; kept across pages (id → title). */
export const useDocumentSelection = () => {
  const [selected, setSelected] = useState<Map<string, string>>(new Map());

  const toggle = useCallback((doc: SelectableDoc) => {
    const id = docKey(doc);
    if (!id) return;
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.set(id, doc.title || 'Untitled');
      }
      return next;
    });
  }, []);

  /** Tick (or untick) every document on the current page. */
  const setPage = useCallback((docs: SelectableDoc[], checked: boolean) => {
    setSelected((prev) => {
      const next = new Map(prev);
      docs.forEach((doc) => {
        const id = docKey(doc);
        if (!id) return;
        if (checked) next.set(id, doc.title || 'Untitled');
        else next.delete(id);
      });
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelected(new Map()), []);

  const isSelected = useCallback((doc: SelectableDoc) => selected.has(docKey(doc)), [selected]);

  const documents = Array.from(selected, ([id, title]) => ({ id, title }));

  return { selected, documents, count: selected.size, toggle, setPage, clear, isSelected };
};

export type DocumentSelection = ReturnType<typeof useDocumentSelection>;
