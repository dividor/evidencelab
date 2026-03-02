import React, { useState } from 'react';
import { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import GroupManager from './GroupManager';
import GroupSettingsManager from './GroupSettingsManager';
import UserManager from './UserManager';

interface AdminPanelProps {
  isActive: boolean;
}

type AdminTab = 'users' | 'groups' | 'group-settings';

const AdminPanel: React.FC<AdminPanelProps> = ({ isActive }) => {
  const { user } = useAuth();
  const [tab, setTab] = useState<AdminTab>('users');

  if (!USER_MODULE || !isActive || !user?.is_superuser) return null;

  return (
    <div className="admin-panel">
      <div className="admin-header">
        <h2>Administration</h2>
        <div className="admin-tabs">
          <button
            className={`admin-tab ${tab === 'users' ? 'admin-tab-active' : ''}`}
            onClick={() => setTab('users')}
          >
            Users
          </button>
          <button
            className={`admin-tab ${tab === 'groups' ? 'admin-tab-active' : ''}`}
            onClick={() => setTab('groups')}
          >
            Groups
          </button>
          <button
            className={`admin-tab ${tab === 'group-settings' ? 'admin-tab-active' : ''}`}
            onClick={() => setTab('group-settings')}
          >
            Group Settings
          </button>
        </div>
      </div>
      <div className="admin-tab-content">
        {tab === 'users' && <UserManager />}
        {tab === 'groups' && <GroupManager />}
        {tab === 'group-settings' && <GroupSettingsManager />}
      </div>
    </div>
  );
};

export default AdminPanel;
