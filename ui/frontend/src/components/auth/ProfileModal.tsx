import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { useAuth } from '../../hooks/useAuth';

interface ProfileModalProps {
  onClose: () => void;
}

type ProfileTab = 'profile' | 'groups';

const ProfileModal: React.FC<ProfileModalProps> = ({ onClose }) => {
  const { user, refreshUser } = useAuth();
  const [tab, setTab] = useState<ProfileTab>('profile');
  const [displayName, setDisplayName] = useState(user?.display_name || '');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [groups, setGroups] = useState<Array<{ id: string; name: string; description: string | null }>>([]);

  useEffect(() => {
    if (tab === 'groups') {
      axios.get(`${API_BASE_URL}/users/me/groups`).then((resp) => {
        setGroups(resp.data);
      }).catch(() => {});
    }
  }, [tab]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage('');
    try {
      await axios.patch(`${API_BASE_URL}/users/me`, { display_name: displayName });
      await refreshUser();
      setMessage('Profile updated');
    } catch {
      setMessage('Failed to update profile');
    } finally {
      setSaving(false);
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
          </div>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="modal-body">
          {tab === 'profile' && (
            <form onSubmit={handleSave}>
              {message && <div className="auth-success">{message}</div>}
              <div className="form-group">
                <label htmlFor="profile-email">Email</label>
                <input id="profile-email" type="email" value={user.email} disabled />
              </div>
              <div className="form-group">
                <label htmlFor="profile-name">Display Name</label>
                <input
                  id="profile-name"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Your name"
                />
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
        </div>
      </div>
    </div>
  );
};

export default ProfileModal;
