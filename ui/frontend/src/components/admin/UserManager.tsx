import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import type { AuthUser } from '../../types/auth';

const UserManager: React.FC = () => {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

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

  if (loading) return <div className="admin-loading">Loading users...</div>;
  if (error) return <div className="auth-error">{error}</div>;

  return (
    <div className="admin-section">
      <h3>Users ({users.length})</h3>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Name</th>
            <th>Active</th>
            <th>Verified</th>
            <th>Admin</th>
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default UserManager;
