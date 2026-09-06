import React, { useCallback, useRef, useState } from 'react';
import { ResolvedTab, TAB_TOOLTIPS, TabKey, resolveTabs } from './tabConfig';
import { useCloseOnOutsideClick } from '../../hooks/useCloseOnOutsideClick';

type TabName = 'search' | 'assistant' | 'brief' | 'heatmap' | 'documents' | 'pipeline' | 'processing' | 'info' | 'tech' | 'data' | 'privacy' | 'terms' | 'stats' | 'admin' | 'docs';

interface NavTabsProps {
  activeTab: TabName;
  onTabChange: (tab: TabName) => void;
  // Resolved per-group tab visibility/labels. When omitted, every main tab
  // shows with its default label (stock behaviour).
  tabs?: Record<TabKey, ResolvedTab>;
}

const ACTIVE_CLASS = 'nav-tab-active';
const MAIN_TABS: TabKey[] = ['search', 'assistant', 'brief', 'heatmap'];

export const NavTabs = ({ activeTab, onTabChange, tabs }: NavTabsProps) => {
  const resolved = tabs ?? resolveTabs(undefined);
  const [monitorDropdownOpen, setMonitorDropdownOpen] = useState(false);
  const monitorRef = useRef<HTMLDivElement>(null);
  const closeMonitorDropdown = useCallback(() => setMonitorDropdownOpen(false), []);
  useCloseOnOutsideClick(monitorRef, monitorDropdownOpen, closeMonitorDropdown);
  const monitorActive = activeTab === 'documents' || activeTab === 'pipeline' || activeTab === 'processing' || activeTab === 'stats';

  const handleToggleMonitorDropdown = () => {
    setMonitorDropdownOpen((open) => !open);
  };

  const handleMonitorSelect = (tab: 'documents' | 'pipeline' | 'processing' | 'stats') => {
    onTabChange(tab);
    setMonitorDropdownOpen(false);
  };

  return (
    <nav className="nav-tabs">
      {MAIN_TABS.map((key) =>
        resolved[key].enabled ? (
          <button
            key={key}
            className={`nav-tab ${activeTab === key ? ACTIVE_CLASS : ''}`}
            onClick={() => onTabChange(key)}
            aria-label={resolved[key].label}
            aria-describedby={`nav-tab-tip-${key}`}
          >
            {resolved[key].label}
            <span className="nav-tab-tooltip" role="tooltip" id={`nav-tab-tip-${key}`}>
              {TAB_TOOLTIPS[key]}
            </span>
          </button>
        ) : null,
      )}
      <div className="dropdown-container nav-dropdown" ref={monitorRef}>
        <button
          className={`nav-tab nav-tab-dropdown ${monitorActive ? ACTIVE_CLASS : ''}`}
          onClick={handleToggleMonitorDropdown}
        >
          <span>Monitor</span>
          <span className="dropdown-arrow">▾</span>
        </button>
        {monitorDropdownOpen && (
          <div className="dropdown-menu nav-dropdown-menu">
            <button className="dropdown-item" onClick={() => handleMonitorSelect('pipeline')}>
              Pipeline
            </button>
            <button className="dropdown-item" onClick={() => handleMonitorSelect('stats')}>
              Stats
            </button>
            <button className="dropdown-item" onClick={() => handleMonitorSelect('processing')}>
              Processing
            </button>
            <button className="dropdown-item" onClick={() => handleMonitorSelect('documents')}>
              Documents
            </button>
          </div>
        )}
      </div>
    </nav>
  );
};
