import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import type { GroupMember, UserGroup } from '../../types/auth';

interface GroupManagerProps {
  /** All datasource keys from config (to populate checkboxes). */
  availableDatasources: string[];
}

const GroupManager: React.FC<GroupManagerProps> = ({ availableDatasources }) => {
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<UserGroup | null>(null);
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // New group form
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupDesc, setNewGroupDesc] = useState('');

  // Add member form
  const [addMemberEmail, setAddMemberEmail] = useState('');

  const fetchGroups = useCallback(async () => {
    try {
      const resp = await axios.get<UserGroup[]>(`${API_BASE_URL}/groups/`);
      setGroups(resp.data);
    } catch {
      setError('Failed to load groups');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  const selectGroup = async (group: UserGroup) => {
    setSelectedGroup(group);
    try {
      const resp = await axios.get<GroupMember[]>(`${API_BASE_URL}/groups/${group.id}/members`);
      setMembers(resp.data);
    } catch {
      setMembers([]);
    }
  };

  const createGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newGroupName.trim()) return;
    try {
      await axios.post(`${API_BASE_URL}/groups/`, {
        name: newGroupName.trim(),
        description: newGroupDesc.trim() || null,
      });
      setNewGroupName('');
      setNewGroupDesc('');
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create group');
    }
  };

  const deleteGroup = async (groupId: string) => {
    if (!window.confirm('Delete this group?')) return;
    try {
      await axios.delete(`${API_BASE_URL}/groups/${groupId}`);
      if (selectedGroup?.id === groupId) {
        setSelectedGroup(null);
        setMembers([]);
      }
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete group');
    }
  };

  const toggleDatasource = async (groupId: string, dsKey: string, current: string[]) => {
    const newKeys = current.includes(dsKey)
      ? current.filter((k) => k !== dsKey)
      : [...current, dsKey];
    try {
      const resp = await axios.put<UserGroup>(`${API_BASE_URL}/groups/${groupId}/datasources`, {
        datasource_keys: newKeys,
      });
      setSelectedGroup(resp.data);
      await fetchGroups();
    } catch {
      setError('Failed to update datasources');
    }
  };

  const removeMember = async (userId: string) => {
    if (!selectedGroup) return;
    try {
      await axios.delete(`${API_BASE_URL}/groups/${selectedGroup.id}/members/${userId}`);
      setMembers(members.filter((m) => m.id !== userId));
      await fetchGroups();
    } catch {
      setError('Failed to remove member');
    }
  };

  const addMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedGroup || !addMemberEmail.trim()) return;
    // We need the user ID — fetch all users and find by email
    try {
      const resp = await axios.get(`${API_BASE_URL}/users/all`);
      const found = resp.data.find((u: any) => u.email === addMemberEmail.trim());
      if (!found) {
        setError(`User not found: ${addMemberEmail}`);
        return;
      }
      await axios.post(`${API_BASE_URL}/groups/${selectedGroup.id}/members`, {
        user_id: found.id,
      });
      setAddMemberEmail('');
      await selectGroup(selectedGroup);
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add member');
    }
  };

  if (loading) return <div className="admin-loading">Loading groups...</div>;

  return (
    <div className="admin-section">
      <h3>Groups</h3>
      {error && <div className="auth-error">{error}<button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button></div>}

      <div className="admin-two-col">
        {/* Left: group list */}
        <div className="admin-col">
          <form onSubmit={createGroup} className="admin-inline-form">
            <input
              type="text"
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              placeholder="New group name"
              required
            />
            <input
              type="text"
              value={newGroupDesc}
              onChange={(e) => setNewGroupDesc(e.target.value)}
              placeholder="Description (optional)"
            />
            <button type="submit" className="btn-sm">Create</button>
          </form>

          <table className="admin-table">
            <thead>
              <tr>
                <th>Group</th>
                <th>Members</th>
                <th>Datasources</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr
                  key={g.id}
                  className={selectedGroup?.id === g.id ? 'admin-row-selected' : ''}
                  onClick={() => selectGroup(g)}
                >
                  <td>
                    {g.name}
                    {g.is_default && <span className="badge badge-default">Default</span>}
                  </td>
                  <td>{g.member_count}</td>
                  <td>{g.datasource_keys.length || 'All'}</td>
                  <td>
                    {!g.is_default && (
                      <button
                        className="btn-sm btn-danger"
                        onClick={(e) => { e.stopPropagation(); deleteGroup(g.id); }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Right: selected group detail */}
        {selectedGroup && (
          <div className="admin-col">
            <h4>{selectedGroup.name} — Datasource Access</h4>
            <p className="text-muted">
              {selectedGroup.is_default
                ? 'Default group has access to all datasources.'
                : 'Check the datasources this group can access.'}
            </p>
            {!selectedGroup.is_default && (
              <div className="admin-checkbox-list">
                {availableDatasources.map((ds) => (
                  <label key={ds} className="admin-checkbox">
                    <input
                      type="checkbox"
                      checked={selectedGroup.datasource_keys.includes(ds)}
                      onChange={() => toggleDatasource(selectedGroup.id, ds, selectedGroup.datasource_keys)}
                    />
                    {ds}
                  </label>
                ))}
              </div>
            )}

            <h4>Members</h4>
            <form onSubmit={addMember} className="admin-inline-form">
              <input
                type="email"
                value={addMemberEmail}
                onChange={(e) => setAddMemberEmail(e.target.value)}
                placeholder="user@example.com"
                required
              />
              <button type="submit" className="btn-sm">Add</button>
            </form>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Name</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id}>
                    <td>{m.email}</td>
                    <td>{m.display_name || '-'}</td>
                    <td>
                      <button className="btn-sm btn-danger" onClick={() => removeMember(m.id)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
                {members.length === 0 && (
                  <tr><td colSpan={3} className="text-muted">No members</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default GroupManager;
