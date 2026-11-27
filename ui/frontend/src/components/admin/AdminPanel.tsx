import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { useCloseOnOutsideClick } from '../../hooks/useCloseOnOutsideClick';
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

const SAVED_BRIEFS_PAGE = 'testing-brief';

const adminTabs = [
  ['users', 'Users'],
  ['groups', 'Groups'],
  ['group-settings', 'Group Settings'],
  ['ratings', 'Ratings'],
  ['activity', 'Activity'],
  ['llm-usage', 'LLM Usage'],
  ['mcp-audit', 'MCP / A2A'],
  ['api-keys', 'API Keys'],
  ['testing', 'Testing'],
  ['toc-validator', 'TOC Validator'],
] as const;

function AdminNavigation({ tab }: { tab: string }) {
  const header = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [anchor, setAnchor] = useState<{ left: number; top: number } | null>(null);
  const open = anchor !== null;
  const close = useCallback(() => setAnchor(null), []);
  useCloseOnOutsideClick(header, open, close);

  const select = (page: string) => {
    close();
    openAdminLocation({ page });
    trigger.current?.focus();
  };
  const alignMenu = useCallback(() => {
    if (!trigger.current || !header.current) return;
    const button = trigger.current.getBoundingClientRect();
    const container = header.current.getBoundingClientRect();
    setAnchor({ left: button.left - container.left, top: button.bottom - container.top });
  }, []);
  useLayoutEffect(() => {
    if (!open || !header.current) return;
    const observer = new ResizeObserver(alignMenu);
    observer.observe(header.current);
    return () => observer.disconnect();
  }, [open, alignMenu]);
  const testingActive = tab === 'testing' || tab === SAVED_BRIEFS_PAGE;
  return <div className="admin-header" ref={header} onKeyDown={event => {
    if (event.key === 'Escape' && open) trigger.current?.focus();
  }} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close();
  }}>
    <h2>Administration</h2>
    <div className="admin-tabs">
      {adminTabs.map(([key, label]) => key === 'testing' ? (
        <button type="button" key={key} ref={trigger}
          className={`admin-tab nav-tab-dropdown ${testingActive ? 'admin-tab-active' : ''}`}
          aria-expanded={open} aria-controls="admin-testing-choices"
          onClick={open ? close : alignMenu}>
          {label}<span className="dropdown-arrow" aria-hidden="true">▾</span>
        </button>
      ) : (
        <button type="button" key={key} className={`admin-tab ${tab === key ? 'admin-tab-active' : ''}`}
          onClick={() => { close(); if (key !== tab) openAdminLocation({ page: key }); }}>{label}</button>
      ))}
    </div>
    {anchor && <div className="dropdown-menu admin-testing-choices" id="admin-testing-choices"
      role="group" aria-label="Testing" style={{ top: anchor.top, left: `clamp(0px, ${anchor.left}px, 100% - 11rem)` }}>
      <button autoFocus type="button" className="dropdown-item" onClick={() => select('testing')}>Experiments</button>
      <button type="button" className="dropdown-item" onClick={() => select(SAVED_BRIEFS_PAGE)}>Saved Briefs</button>
    </div>}
  </div>;
}

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
  const tab = page === SAVED_BRIEFS_PAGE ? page : adminTabs.find(([key]) => key === page)?.[0] ?? 'users';

  if (!USER_MODULE || !isActive || !user?.is_superuser) return null;

  return (
    <div className="admin-panel">
      <AdminNavigation tab={tab} />
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
        {tab === SAVED_BRIEFS_PAGE && (
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
