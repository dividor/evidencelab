import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { useAuth } from '../../hooks/useAuth';
import type { AuthUser } from '../../types/auth';
import ConfirmModal from './ConfirmModal';

/* ------------------------------------------------------------------ */
/*  Create-user modal                                                 */
/* ------------------------------------------------------------------ */

interface CreateUserModalProps {
  onCreated: () => void;
  onCancel: () => void;
}

const CreateUserModal: React.FC<CreateUserModalProps> = ({ onCreated, onCancel }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setCreating(true);
    try {
      await axios.post(`${API_BASE_URL}/users/create`, {
        email,
        password,
        display_name: displayName || undefined,
      });
      onCreated();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create user');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Create User</h3>
          <button className="modal-close" onClick={onCancel}>&times;</button>
        </div>
        <div className="modal-body">
          {error && <div className="auth-error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="create-email">Email</label>
              <input
                id="create-email"
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
              />
            </div>
            <div className="form-group">
              <label htmlFor="create-password">Password</label>
              <input
                id="create-password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 8 chars, 1 letter, 1 digit"
              />
            </div>
            <div className="form-group">
              <label htmlFor="create-name">Display name (optional)</label>
              <input
                id="create-name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Jane Doe"
              />
            </div>
            <button type="submit" className="auth-submit" disabled={creating}>
              {creating ? 'Creating...' : 'Create User'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Main user manager                                                 */
/* ------------------------------------------------------------------ */

const UserManager: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; email: string } | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState('');

  const fetchUsers = useCallback(async () => {
    try {
      const resp = await axios.get<AuthUser[]>(`${API_BASE_URL}/users/all`);
      setUsers(resp.data);
    } catch {
      setError('Failed to load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const toggleFlag = async (userId: string, flag: string, value: boolean) => {
    try {
      await axios.patch(`${API_BASE_URL}/users/${userId}/flags`, null, {
        params: { [flag]: value },
      });
      await fetchUsers();
    } catch {
      setError(`Failed to update ${flag}`);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await axios.delete(`${API_BASE_URL}/users/${deleteTarget.id}`);
      setDeleteTarget(null);
      await fetchUsers();
    } catch (err: any) {
      setDeleteTarget(null);
      setError(err.response?.data?.detail || 'Failed to delete user');
    }
  };

  const filteredUsers = search
    ? users.filter((u) => {
        const term = search.toLowerCase();
        return (
          u.email.toLowerCase().includes(term) ||
          (u.display_name || '').toLowerCase().includes(term)
        );
      })
    : users;

  if (loading) return <div className="admin-loading">Loading users...</div>;

  return (
    <div className="admin-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}
      <div className="admin-controls" style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          placeholder="Search by email or name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="admin-search-input"
          style={{ minWidth: '220px', padding: '0.4rem 0.6rem', borderRadius: '4px', border: '1px solid #ccc', fontSize: '0.85rem' }}
        />
        <p className="text-muted" style={{ margin: 0 }}>
          {filteredUsers.length}{search ? ` of ${users.length}` : ''} user{filteredUsers.length !== 1 ? 's' : ''}
        </p>
        <button className="btn-sm btn-primary" onClick={() => setShowCreate(true)} style={{ marginLeft: 'auto' }}>
          + Create User
        </button>
      </div>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Name</th>
            <th>Active</th>
            <th>Verified</th>
            <th>Admin</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {filteredUsers.map((u) => (
            <tr key={u.id}>
              <td>{u.email}</td>
              <td>{u.display_name || '-'}</td>
              <td>
                <input
                  type="checkbox"
                  checked={u.is_active}
                  onChange={(e) => toggleFlag(u.id, 'is_active', e.target.checked)}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={u.is_verified}
                  onChange={(e) => toggleFlag(u.id, 'is_verified', e.target.checked)}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={u.is_superuser}
                  onChange={(e) => toggleFlag(u.id, 'is_superuser', e.target.checked)}
                />
              </td>
              <td>
                {u.id !== currentUser?.id && (
                  <button
                    className="btn-sm btn-danger"
                    onClick={() => setDeleteTarget({ id: u.id, email: u.email })}
                  >
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {deleteTarget && (
        <ConfirmModal
          title="Delete User"
          message={`Permanently delete ${deleteTarget.email}? This will remove all their data including group memberships and OAuth links. This action cannot be undone.`}
          confirmLabel="Delete User"
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {showCreate && (
        <CreateUserModal
          onCreated={() => {
            setShowCreate(false);
            fetchUsers();
          }}
          onCancel={() => setShowCreate(false)}
        />
      )}
    </div>
  );
};

export default UserManager;
