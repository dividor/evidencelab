import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';

interface UseDocumentLogsParams {
  isOpen: boolean;
  docId: string;
  dataSource: string;
}

interface LogsResponse {
  logs?: string;
  error?: string;
  source?: string;
  stderr?: string;
}

export const useDocumentLogs = ({
  isOpen,
  docId,
  dataSource
}: UseDocumentLogsParams) => {
  const [logs, setLogs] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<LogsResponse>(
        `${API_BASE_URL}/document/${docId}/logs`,
        { params: { data_source: dataSource } }
      );
      if (response.data.error) {
        setError(response.data.error);
        setLogs('');
      } else {
        setLogs(response.data.logs || '');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to load logs');
      setLogs('');
    } finally {
      setLoading(false);
    }
  }, [docId, dataSource]);

  useEffect(() => {
    if (isOpen && docId) {
      loadLogs();
    }
  }, [isOpen, docId, loadLogs]);

  return {
    logs,
    loading,
    error,
    reload: loadLogs
  };
};
