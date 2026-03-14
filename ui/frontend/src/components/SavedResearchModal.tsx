import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';

interface SavedResearchItem {
  id: string;
  title: string;
  query: string;
  data_source: string | null;
  node_count: number;
  created_at: string;
  updated_at: string;
}

interface SavedResearchModalProps {
  onClose: () => void;
  onLoadResearch: (id: string) => void;
}

const formatDate = (dateStr: string) => {
  const d = new Date(dateStr);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

const SavedResearchModal: React.FC<SavedResearchModalProps> = ({ onClose, onLoadResearch }) => {
  const [research, setResearch] = useState<SavedResearchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    axios.get<SavedResearchItem[]>(`${API_BASE_URL}/research/`).then((resp) => {
      setResearch(resp.data);
    }).catch(() => {}).then(() => setLoading(false));
  }, []);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeletingId(id);
    try {
      await axios.delete(`${API_BASE_URL}/research/${id}`);
      setResearch((prev) => prev.filter((r) => r.id !== id));
    } catch {
      // Silently fail
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content profile-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ margin: 0 }}>Load Previous Research</h3>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">
          {loading && <p className="text-muted">Loading saved research...</p>}
          {!loading && research.length === 0 && (
            <p className="text-muted">No saved research yet.</p>
          )}
          {!loading && research.length > 0 && (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Query</th>
                  <th>Nodes</th>
                  <th>Saved</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {research.map((r) => (
                  <tr
                    key={r.id}
                    className="saved-research-row"
                    onClick={() => onLoadResearch(r.id)}
                    title="Click to load this research"
                  >
                    <td>{r.title}</td>
                    <td>{r.query}</td>
                    <td>{r.node_count}</td>
                    <td>{formatDate(r.updated_at)}</td>
                    <td>
                      <button
                        className="btn-danger-sm"
                        onClick={(e) => handleDelete(r.id, e)}
                        disabled={deletingId === r.id}
                        title="Delete this saved research"
                      >
                        {deletingId === r.id ? '...' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};

export default SavedResearchModal;
