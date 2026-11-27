import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';

/** Mounted with a key for the requested record, including on history navigation. */
export default function SavedEvaluationRecord<T>({ id, collection, onBack, children }: {
  id: string;
  collection: 'datasets' | 'experiments';
  onBack: () => void;
  children: (record: T) => React.ReactNode;
}) {
  const [record, setRecord] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  const label = collection === 'datasets' ? 'dataset' : 'experiment';

  useEffect(() => {
    const controller = new AbortController();
    axios.get<T>(`${API_BASE_URL}/testing/${collection}/${encodeURIComponent(id)}`, {signal: controller.signal})
      .then(({data}) => { if (!controller.signal.aborted) setRecord(data); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [collection, id]);

  if (failed) return <div role="alert">Could not open this {label}. <button onClick={onBack}>Back to {collection}</button></div>;
  if (!record) return <p role="status">Loading {label}…</p>;
  return <>{children(record)}</>;
}
