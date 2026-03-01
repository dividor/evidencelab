import React, { useState } from 'react';
import { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import GroupManager from './GroupManager';
import UserManager from './UserManager';

interface AdminPanelProps {
  isActive: boolean;
  availableDatasources: string[];
}

type AdminTab = 'users' | 'groups';

const AdminPanel: React.FC<AdminPanelProps> = ({ isActive, availableDatasources }) => {
  const { user } = useAuth();
  const [tab, setTab] = useState<AdminTab>('users');

  if (!USER_MODULE || !isActive || !user?.is_superuser) return null;

  return (
    <div className="admin-panel">
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
      </div>
      {tab === 'users' && <UserManager />}
      {tab === 'groups' && <GroupManager availableDatasources={availableDatasources} />}
    </div>
  );
};

export default AdminPanel;
