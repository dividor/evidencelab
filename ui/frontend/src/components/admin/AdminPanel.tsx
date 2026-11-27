import React from 'react';
import { openAdminLocation, useAdminLocation } from '../../utils/adminLocation';
import { USER_MODULE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import ActivityManager from './ActivityManager';
import ApiKeyManager from './ApiKeyManager';
import GroupManager from './GroupManager';
import GroupSettingsManager from './GroupSettingsManager';
import LlmUsageManager from './LlmUsageManager';
import McpAuditLog from './McpAuditLog';
import RatingsManager from './RatingsManager';
import TestingManager from './TestingManager';
import BriefTestingManager from './BriefTestingManager';
import type { SearchResult, SummaryModelConfig } from '../../types/api';
import TocValidatorManager from './TocValidatorManager';
import UserManager from './UserManager';

interface AdminPanelProps {
  isActive: boolean;
  dataSource?: string;
  dataSourceConfig?: import('../../App').DataSourceConfigItem;
  // The model combo selected at the top of the page; the brief citation check
  // judges with its summarisation model.
  modelCombo?: string | null;
  assistantModelConfig?: SummaryModelConfig | null;
  // Opens a cited document in the app's own preview (as search results do).
  onResultClick?: (result: SearchResult) => void;
}

const adminTabs = [
  ['users', 'Users'],
  ['groups', 'Groups'],
  ['group-settings', 'Group Settings'],
  ['ratings', 'Ratings'],
  ['activity', 'Activity'],
  ['llm-usage', 'LLM Usage'],
  ['mcp-audit', 'MCP / A2A'],
  ['api-keys', 'API Keys'],
  ['testing', 'Testing (Experiments)'],
  ['testing-brief', 'Testing (Saved Briefs)'],
  ['toc-validator', 'TOC Validator'],
] as const;

const AdminPanel: React.FC<AdminPanelProps> = ({
  isActive,
  dataSource = '',
  dataSourceConfig,
  modelCombo = null,
  assistantModelConfig,
  onResultClick,
}) => {
  const { user } = useAuth();
  const { page } = useAdminLocation();
  const tab = adminTabs.find(([key]) => key === page)?.[0] ?? 'users';

  if (!USER_MODULE || !isActive || !user?.is_superuser) return null;

  return (
    <div className="admin-panel">
      <div className="admin-header">
        <h2>Administration</h2>
        <div className="admin-tabs">
          {adminTabs.map(([key, label]) => (
            <button key={key} className={`admin-tab ${tab === key ? 'admin-tab-active' : ''}`}
              onClick={() => { if (key !== tab) openAdminLocation({ page: key }); }}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="admin-tab-content">
        {tab === 'users' && <UserManager />}
        {tab === 'groups' && <GroupManager />}
        {tab === 'group-settings' && <GroupSettingsManager assistantModelConfig={assistantModelConfig} />}
        {tab === 'ratings' && <RatingsManager />}
        {tab === 'activity' && <ActivityManager />}
        {tab === 'llm-usage' && <LlmUsageManager />}
        {tab === 'mcp-audit' && <McpAuditLog />}
        {tab === 'api-keys' && <ApiKeyManager />}
        {tab === 'testing' && <TestingManager />}
        {tab === 'testing-brief' && (
          <BriefTestingManager
            dataSource={dataSource}
            modelCombo={modelCombo}
            onResultClick={onResultClick}
          />
        )}
        {tab === 'toc-validator' && (
          <TocValidatorManager
            dataSource={dataSource}
            dataSourceConfig={dataSourceConfig}
          />
        )}
      </div>
    </div>
  );
};

export default AdminPanel;
