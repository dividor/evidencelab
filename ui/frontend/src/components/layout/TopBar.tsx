import React, { useEffect, useMemo, useState } from 'react';
import { ModelComboConfig } from '../../types/api';
import { USER_MODULE } from '../../config';
import UserMenu from '../auth/UserMenu';
import { ModelComboPanel } from './ModelComboPanel';

interface TopBarProps {
  selectedDomain: string;
  availableDomains: string[];
  datasetTotals: Record<string, number | undefined>;
  selectedModelCombo: string;
  availableModelCombos: string[];
  modelCombos: Record<string, ModelComboConfig>;
  domainDropdownOpen: boolean;
  modelDropdownOpen: boolean;
  helpDropdownOpen: boolean;
  showDomainTooltip: boolean;
  onToggleDomainDropdown: () => void;
  onToggleModelDropdown: () => void;
  onDomainMouseEnter: () => void;
  onDomainMouseLeave: () => void;
  onDomainBlur: () => void;
  onModelBlur: () => void;
  onSelectDomain: (domainName: string) => void;
  onSelectModelCombo: (comboName: string) => void;
  onToggleHelpDropdown: () => void;
  onHelpBlur: () => void;
  onAboutClick: () => void;
  onTechClick: () => void;
  onDataClick: () => void;
  onDocsClick: () => void;
  onAdminClick?: () => void;
  onLoadResearch?: (id: string) => void;
  navTabs?: React.ReactNode;
}

export const TopBar = ({
  selectedDomain,
  availableDomains,
  datasetTotals,
  selectedModelCombo,
  availableModelCombos,
  modelCombos,
  domainDropdownOpen,
  modelDropdownOpen,
  helpDropdownOpen,
  showDomainTooltip,
  onToggleDomainDropdown,
  onToggleModelDropdown,
  onDomainMouseEnter,
  onDomainMouseLeave,
  onDomainBlur,
  onModelBlur,
  onSelectDomain,
  onSelectModelCombo,
  onToggleHelpDropdown,
  onHelpBlur,
  onAboutClick,
  onTechClick,
  onDataClick,
  onDocsClick,
  onAdminClick,
  onLoadResearch,
  navTabs,
}: TopBarProps) => {
  const [hoveredModelCombo, setHoveredModelCombo] = useState<string | null>(null);

  useEffect(() => {
    if (!modelDropdownOpen) {
      setHoveredModelCombo(null);
    }
  }, [modelDropdownOpen]);

  const activeModelCombo = hoveredModelCombo || selectedModelCombo;
  const fallbackComboName = availableModelCombos[0];
  const activeComboConfig =
    modelCombos[activeModelCombo] || modelCombos[fallbackComboName];
  const displayComboName =
    modelCombos[activeModelCombo] ? activeModelCombo : fallbackComboName;

  const numberFormatter = useMemo(() => new Intl.NumberFormat('en-US'), []);

  const modelTriggerMinWidth = useMemo(() => {
    if (!availableModelCombos.length) {
      return undefined;
    }
    const longestCombo = availableModelCombos.reduce(
      (longest, current) => (current.length > longest.length ? current : longest),
      ''
    );
    const charCount = 'Models'.length + longestCombo.length + 1;
    return `calc(${charCount}ch + 3.5rem)`;
  }, [availableModelCombos]);

  const getDomainLabelText = (domainName: string) => {
    const total = datasetTotals[domainName];
    if (total === undefined || Number.isNaN(total)) {
      return domainName;
    }
    return `${domainName} (${numberFormatter.format(total)})`;
  };

  const renderDomainLabel = (domainName: string) => {
    const total = datasetTotals[domainName];
    if (total === undefined || Number.isNaN(total)) {
      return domainName;
    }
    return (
      <>
        {domainName} <span className="dataset-total">({numberFormatter.format(total)})</span>
      </>
    );
  };

  const datasetTriggerMinWidth = useMemo(() => {
    if (!availableDomains.length) {
      return undefined;
    }
    const longestLabel = availableDomains.reduce((longest, current) => {
      const label = getDomainLabelText(current);
      return label.length > longest.length ? label : longest;
    }, '');
    const charCount = 'Dataset'.length + longestLabel.length;
    return `calc(${charCount}ch + 1.5rem)`;
  }, [availableDomains, getDomainLabelText]);

  return (
    <header className="top-bar">
      <div className="top-bar-content">
        <div className="top-bar-left">
          <div className="top-bar-brand">
            <img src="/logo.png" alt="Evidence Lab Logo" className="app-logo" />
            <h1 className="app-title">Evidence Lab</h1>
          </div>
          <div className="top-bar-controls">
            <div className="dropdown-container">
            <button
              className="dropdown-trigger dropdown-trigger-domain"
              onClick={onToggleDomainDropdown}
              onMouseEnter={onDomainMouseEnter}
              onMouseLeave={onDomainMouseLeave}
              onBlur={onDomainBlur}
              style={datasetTriggerMinWidth ? { minWidth: datasetTriggerMinWidth } : undefined}
            >
              <span className="dropdown-label">Dataset</span>
              <span className="dropdown-value">{renderDomainLabel(selectedDomain)}</span>
              <span className="dropdown-arrow">▾</span>
            </button>
            {showDomainTooltip && !domainDropdownOpen && (
              <div className="tooltip-text">
                Select the data domain you want to experiment with
              </div>
            )}
            {domainDropdownOpen && (
              <div className="dropdown-menu dropdown-menu-domain">
                {availableDomains.map((domainName) => (
                  <button
                    key={domainName}
                    className="dropdown-item"
                    onClick={() => onSelectDomain(domainName)}
                  >
                    {renderDomainLabel(domainName)}
                  </button>
                ))}
              </div>
            )}
          </div>

            <div className="dropdown-container">
            <button
              className="dropdown-trigger"
              onClick={onToggleModelDropdown}
              onBlur={onModelBlur}
              style={modelTriggerMinWidth ? { minWidth: modelTriggerMinWidth } : undefined}
            >
              <span className="dropdown-label">Models</span>
              <span className="dropdown-value">{selectedModelCombo}</span>
              <span className="dropdown-arrow">▾</span>
            </button>
            {modelDropdownOpen && (
              <div
                className="dropdown-menu dropdown-menu-models"
              >
                <div className="dropdown-menu-list">
                  {availableModelCombos.map((comboName) => (
                    <button
                      key={comboName}
                      className="dropdown-item"
                      onClick={() => onSelectModelCombo(comboName)}
                      onMouseEnter={() => setHoveredModelCombo(comboName)}
                    >
                      {comboName}
                    </button>
                  ))}
                </div>
                {activeComboConfig && (
                  <ModelComboPanel config={activeComboConfig} displayName={displayComboName} />
                )}
              </div>
            )}
            </div>
          </div>
        </div>

        <div className="top-bar-right">
          <div className="dropdown-container">
            <button
              className="dropdown-trigger dropdown-trigger-help"
              onClick={onToggleHelpDropdown}
              onBlur={onHelpBlur}
            >
              <span className="dropdown-value">Info</span>
              <span className="dropdown-arrow">▾</span>
            </button>
            {helpDropdownOpen && (
              <div className="dropdown-menu dropdown-menu-help">
                <button className="dropdown-item" onClick={onAboutClick}>
                  About
                </button>
                <button className="dropdown-item" onClick={onTechClick}>
                  Tech
                </button>
                <button className="dropdown-item" onClick={onDataClick}>
                  Data
                </button>
                <button className="dropdown-item" onClick={onDocsClick}>
                  Docs
                </button>
              </div>
            )}
          </div>
          {USER_MODULE && <UserMenu onAdminClick={onAdminClick} onLoadResearch={onLoadResearch} />}
        </div>
      </div>
      {navTabs}
    </header>
  );
};
