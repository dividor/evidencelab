import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import type { AuthUser, GroupMember, UserGroup } from '../../types/auth';
import ConfirmModal from './ConfirmModal';

const GroupManager: React.FC = () => {
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<UserGroup | null>(null);
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [allUsers, setAllUsers] = useState<AuthUser[]>([]);
  const [availableDatasources, setAvailableDatasources] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // New group form
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupDesc, setNewGroupDesc] = useState('');

  // Add member picker
  const [selectedUserId, setSelectedUserId] = useState('');

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

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

  const fetchAllUsers = useCallback(async () => {
    try {
      const resp = await axios.get<AuthUser[]>(`${API_BASE_URL}/users/all`);
      setAllUsers(resp.data);
    } catch {
      // Non-critical — picker will be empty
    }
  }, []);

  const fetchDatasources = useCallback(async () => {
    try {
      const resp = await axios.get<string[]>(`${API_BASE_URL}/groups/datasource-keys`);
      setAvailableDatasources(resp.data);
    } catch {
      // Non-critical — datasource picker will be empty
    }
  }, []);

  useEffect(() => {
    fetchGroups();
    fetchAllUsers();
    fetchDatasources();
  }, [fetchGroups, fetchAllUsers, fetchDatasources]);

  // Auto-select the default group on first load
  useEffect(() => {
    if (groups.length > 0 && selectedGroup === null) {
      const defaultGroup = groups.find((g) => g.is_default);
      if (defaultGroup) {
        selectGroup(defaultGroup);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups]);

  const selectGroup = async (group: UserGroup) => {
    setSelectedGroup(group);
    setSelectedUserId('');
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

  const confirmDeleteGroup = async () => {
    if (!deleteTarget) return;
    try {
      await axios.delete(`${API_BASE_URL}/groups/${deleteTarget.id}`);
      if (selectedGroup?.id === deleteTarget.id) {
        setSelectedGroup(null);
        setMembers([]);
      }
      setDeleteTarget(null);
      await fetchGroups();
    } catch (err: any) {
      setDeleteTarget(null);
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
    if (!selectedGroup || !selectedUserId) return;
    try {
      await axios.post(`${API_BASE_URL}/groups/${selectedGroup.id}/members`, {
        user_id: selectedUserId,
      });
      setSelectedUserId('');
      await selectGroup(selectedGroup);
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add member');
    }
  };

  // Users not already in the selected group (for the picker dropdown)
  const memberIds = new Set(members.map((m) => m.id));
  const availableUsers = allUsers.filter((u) => !memberIds.has(u.id));

  if (loading) return <div className="admin-loading">Loading groups...</div>;

  return (
    <div className="admin-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}

      <div className="admin-groups-layout">
        {/* Left: group list */}
        <div className="admin-groups-list">
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
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    {g.name}
                    {g.is_default && <span className="badge badge-default">Default</span>}
                  </td>
                  <td>{g.member_count}</td>
                  <td>{g.datasource_keys.length}</td>
                  <td>
                    {!g.is_default && (
                      <button
                        className="btn-sm btn-danger"
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget({ id: g.id, name: g.name }); }}
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
          <div className="admin-group-detail">
            <h4>Datasource Access</h4>
            {availableDatasources.length === 0 ? (
              <p className="text-muted">No datasources configured.</p>
            ) : (
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

            <h4>Members ({members.length})</h4>
            <form onSubmit={addMember} className="admin-inline-form">
              <select
                value={selectedUserId}
                onChange={(e) => setSelectedUserId(e.target.value)}
                className="admin-select"
              >
                <option value="">Select a user to add...</option>
                {availableUsers.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.email}{u.display_name ? ` (${u.display_name})` : ''}
                  </option>
                ))}
              </select>
              <button type="submit" className="btn-sm" disabled={!selectedUserId}>Add</button>
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

      {deleteTarget && (
        <ConfirmModal
          title="Delete Group"
          message={`Delete the group "${deleteTarget.name}"? Members will lose access granted through this group.`}
          confirmLabel="Delete Group"
          onConfirm={confirmDeleteGroup}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
};

export default GroupManager;
