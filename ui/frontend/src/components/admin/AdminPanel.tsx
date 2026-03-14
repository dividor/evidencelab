import React, { useState } from 'react';
import { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import ActivityManager from './ActivityManager';
import GroupManager from './GroupManager';
import GroupSettingsManager from './GroupSettingsManager';
import RatingsManager from './RatingsManager';
import UserManager from './UserManager';

interface AdminPanelProps {
  isActive: boolean;
}

type AdminTab = 'users' | 'groups' | 'group-settings' | 'ratings' | 'activity';

const TAB_USERS: AdminTab = 'users';
const TAB_GROUPS: AdminTab = 'groups';
const TAB_GROUP_SETTINGS: AdminTab = 'group-settings';
const TAB_RATINGS: AdminTab = 'ratings';
const TAB_ACTIVITY: AdminTab = 'activity';
const ACTIVE_CLASS = 'admin-tab-active';

const tabClass = (tab: AdminTab, current: AdminTab) =>
  `admin-tab ${tab === current ? ACTIVE_CLASS : ''}`;

const AdminPanel: React.FC<AdminPanelProps> = ({ isActive }) => {
  const { user } = useAuth();
  const [tab, setTab] = useState<AdminTab>(TAB_USERS);

  if (!USER_MODULE || !isActive || !user?.is_superuser) return null;

  return (
    <div className="admin-panel">
      <div className="admin-header">
        <h2>Administration</h2>
        <div className="admin-tabs">
          <button
            className={tabClass(tab, TAB_USERS)}
            onClick={() => setTab(TAB_USERS)}
          >
            Users
          </button>
          <button
            className={tabClass(tab, TAB_GROUPS)}
            onClick={() => setTab(TAB_GROUPS)}
          >
            Groups
          </button>
          <button
            className={tabClass(tab, TAB_GROUP_SETTINGS)}
            onClick={() => setTab(TAB_GROUP_SETTINGS)}
          >
            Group Settings
          </button>
          <button
            className={tabClass(tab, TAB_RATINGS)}
            onClick={() => setTab(TAB_RATINGS)}
          >
            Ratings
          </button>
          <button
            className={tabClass(tab, TAB_ACTIVITY)}
            onClick={() => setTab(TAB_ACTIVITY)}
          >
            Activity
          </button>
        </div>
      </div>
      <div className="admin-tab-content">
        {tab === TAB_USERS && <UserManager />}
        {tab === TAB_GROUPS && <GroupManager />}
        {tab === TAB_GROUP_SETTINGS && <GroupSettingsManager />}
        {tab === TAB_RATINGS && <RatingsManager />}
        {tab === TAB_ACTIVITY && <ActivityManager />}
      </div>
    </div>
  );
};

export default AdminPanel;
