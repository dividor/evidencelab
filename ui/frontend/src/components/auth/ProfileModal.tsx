import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { useAuth } from '../../hooks/useAuth';

interface SavedResearchItem {
  id: string;
  title: string;
  query: string;
  data_source: string | null;
  node_count: number;
  created_at: string;
  updated_at: string;
}

/** Saved Research tab content — extracted to reduce ProfileModal complexity */
const SavedResearchTab: React.FC<{
  onLoadResearch: (id: string) => void;
}> = ({ onLoadResearch }) => {
  const [research, setResearch] = useState<SavedResearchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    axios.get<SavedResearchItem[]>(`${API_BASE_URL}/research`).then((resp) => {
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

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  };

  if (loading) {
    return <p className="text-muted">Loading saved research...</p>;
  }

  if (research.length === 0) {
    return <p className="text-muted">No saved research yet. Use the AI Summary Tree view to save your research.</p>;
  }

  return (
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
  );
};

interface ProfileModalProps {
  onClose: () => void;
  onLoadResearch?: (id: string) => void;
}

type ProfileTab = 'profile' | 'groups' | 'research';

const ProfileModal: React.FC<ProfileModalProps> = ({ onClose, onLoadResearch }) => {
  const { user, refreshUser, logout } = useAuth();
  const [tab, setTab] = useState<ProfileTab>('profile');
  const [firstName, setFirstName] = useState(user?.first_name || '');
  const [lastName, setLastName] = useState(user?.last_name || '');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [groups, setGroups] = useState<Array<{ id: string; name: string; description: string | null }>>([]);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (tab === 'groups') {
      axios.get<Array<{ id: string; name: string; description: string | null }>>(`${API_BASE_URL}/users/me/groups`).then((resp) => {
        setGroups(resp.data);
      }).catch(() => {});
    }
  }, [tab]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage('');
    try {
      await axios.patch(`${API_BASE_URL}/users/me`, {
        first_name: firstName,
        last_name: lastName,
      });
      await refreshUser();
      setMessage('Profile updated');
    } catch {
      setMessage('Failed to update profile');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirmText !== 'DELETE') return;
    setDeleting(true);
    try {
      await axios.delete(`${API_BASE_URL}/users/me/account`);
      await logout();
      onClose();
    } catch {
      setMessage('Failed to delete account. Please try again.');
      setShowDeleteConfirm(false);
      setDeleteConfirmText('');
    } finally {
      setDeleting(false);
    }
  };

  if (!user) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content profile-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="login-tabs">
            <button
              className={`login-tab ${tab === 'profile' ? 'login-tab-active' : ''}`}
              onClick={() => setTab('profile')}
            >
              Profile
            </button>
            <button
              className={`login-tab ${tab === 'groups' ? 'login-tab-active' : ''}`}
              onClick={() => setTab('groups')}
            >
              Groups
            </button>
            {onLoadResearch && (
              <button
                className={`login-tab ${tab === 'research' ? 'login-tab-active' : ''}`}
                onClick={() => setTab('research')}
              >
                Saved Research
              </button>
            )}
          </div>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="modal-body">
          {tab === 'profile' && (
            <>
              <form onSubmit={handleSave}>
                {message && <div className="auth-success">{message}</div>}
                <div className="form-group">
                  <label htmlFor="profile-email">Email</label>
                  <input id="profile-email" type="email" value={user.email} disabled />
                </div>
                <div className="form-group-row">
                  <div className="form-group">
                    <label htmlFor="profile-first-name">First Name</label>
                    <input
                      id="profile-first-name"
                      type="text"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      placeholder="First name"
                      autoComplete="given-name"
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="profile-last-name">Last Name</label>
                    <input
                      id="profile-last-name"
                      type="text"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      placeholder="Last name"
                      autoComplete="family-name"
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Status</label>
                  <div className="profile-badges">
                    {user.is_verified
                      ? <span className="badge badge-success">Verified</span>
                      : <span className="badge badge-warning">Unverified</span>
                    }
                    {user.is_superuser && <span className="badge badge-admin">Admin</span>}
                  </div>
                </div>
                <button type="submit" className="auth-submit" disabled={saving}>
                  {saving ? 'Saving...' : 'Save Changes'}
                </button>
              </form>

              <div className="account-danger-zone">
                <h4>Danger zone</h4>
                {!showDeleteConfirm ? (
                  <button
                    className="btn-danger-outline"
                    onClick={() => setShowDeleteConfirm(true)}
                  >
                    Delete my account
                  </button>
                ) : (
                  <div className="delete-confirm-box">
                    <p>
                      This will permanently delete your account, group memberships,
                      and all associated data. This action <strong>cannot be undone</strong>.
                    </p>
                    <label htmlFor="delete-confirm-input">
                      Type <strong>DELETE</strong> to confirm:
                    </label>
                    <input
                      id="delete-confirm-input"
                      type="text"
                      value={deleteConfirmText}
                      onChange={(e) => setDeleteConfirmText(e.target.value)}
                      placeholder="DELETE"
                      autoComplete="off"
                    />
                    <div className="delete-confirm-actions">
                      <button
                        className="btn-danger"
                        disabled={deleteConfirmText !== 'DELETE' || deleting}
                        onClick={handleDeleteAccount}
                      >
                        {deleting ? 'Deleting...' : 'Permanently delete account'}
                      </button>
                      <button
                        className="btn-cancel"
                        onClick={() => { setShowDeleteConfirm(false); setDeleteConfirmText(''); }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === 'groups' && (
            <div className="profile-groups">
              {groups.length === 0 ? (
                <p className="text-muted">You are not a member of any groups.</p>
              ) : (
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Group</th>
                      <th>Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((g) => (
                      <tr key={g.id}>
                        <td>{g.name}</td>
                        <td>{g.description || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {tab === 'research' && onLoadResearch && (
            <div className="profile-research">
              <SavedResearchTab onLoadResearch={onLoadResearch} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ProfileModal;
