import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { useAuth } from '../../hooks/useAuth';
import type { AuthUser } from '../../types/auth';
import ConfirmModal from './ConfirmModal';

const UserManager: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; email: string } | null>(null);

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

  if (loading) return <div className="admin-loading">Loading users...</div>;

  return (
    <div className="admin-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}
      <p className="text-muted" style={{ marginBottom: '0.75rem' }}>
        {users.length} registered user{users.length !== 1 ? 's' : ''}
      </p>
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
          {users.map((u) => (
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
    </div>
  );
};

export default UserManager;
