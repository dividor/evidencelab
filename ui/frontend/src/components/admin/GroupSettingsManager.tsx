import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import type { SearchSettings, UserGroup } from '../../types/auth';
import {
  DEFAULT_FIELD_BOOST_FIELDS,
  DEFAULT_SECTION_TYPES,
  SYSTEM_DEFAULTS,
} from '../../utils/searchUrl';

/** Keys that can be overridden per group. */
const SETTING_KEYS: (keyof SearchSettings)[] = [
  'denseWeight',
  'rerank',
  'recencyBoost',
  'recencyWeight',
  'recencyScaleDays',
  'sectionTypes',
  'keywordBoostShortQueries',
  'minChunkSize',
  'semanticHighlighting',
  'autoMinScore',
  'deduplicate',
  'fieldBoost',
  'fieldBoostFields',
];

const SECTION_TYPE_OPTIONS = [
  { value: 'front_matter', label: 'Front Matter' },
  { value: 'executive_summary', label: 'Executive Summary' },
  { value: 'acronyms', label: 'Acronyms' },
  { value: 'context', label: 'Context' },
  { value: 'methodology', label: 'Methodology' },
  { value: 'findings', label: 'Findings' },
  { value: 'conclusions', label: 'Conclusions' },
  { value: 'recommendations', label: 'Recommendations' },
  { value: 'annexes', label: 'Annexes' },
  { value: 'appendix', label: 'Appendix' },
  { value: 'bibliography', label: 'Bibliography' },
  { value: 'other', label: 'Other' },
];

const BOOST_FIELD_OPTIONS = [
  { value: 'country', label: 'Country' },
  { value: 'organization', label: 'Organization' },
  { value: 'document_type', label: 'Document Type' },
  { value: 'language', label: 'Language' },
];

/** Human-readable labels for each setting key. */
const SETTING_LABELS: Record<keyof SearchSettings, string> = {
  denseWeight: 'Search Mode (Dense Weight)',
  rerank: 'Enable Reranker',
  recencyBoost: 'Boost Recent Reports',
  recencyWeight: 'Recency Weight',
  recencyScaleDays: 'Recency Decay Scale (days)',
  sectionTypes: 'Section Types',
  keywordBoostShortQueries: 'Keyword Boost Short Queries',
  minChunkSize: 'Min Chunk Size',
  semanticHighlighting: 'Semantic Highlighting',
  autoMinScore: 'Auto Min Score',
  deduplicate: 'Deduplicate',
  fieldBoost: 'Field Level Boosting',
  fieldBoostFields: 'Field Boost Fields',
};

const GroupSettingsManager: React.FC = () => {
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Which keys are overridden (checked) vs using system default
  const [overrides, setOverrides] = useState<Set<keyof SearchSettings>>(new Set());
  // Current values for all settings (overridden or system default)
  const [values, setValues] = useState<Required<SearchSettings>>({ ...SYSTEM_DEFAULTS });

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

  // When a group is selected, load its search_settings
  useEffect(() => {
    if (!selectedGroupId) {
      setOverrides(new Set());
      setValues({ ...SYSTEM_DEFAULTS });
      return;
    }
    const group = groups.find((g) => g.id === selectedGroupId);
    if (!group) return;

    const settings = group.search_settings || {};
    const newOverrides = new Set<keyof SearchSettings>();
    const newValues: Required<SearchSettings> = { ...SYSTEM_DEFAULTS };

    for (const key of SETTING_KEYS) {
      if (key in settings && settings[key] !== undefined && settings[key] !== null) {
        newOverrides.add(key);
        (newValues as any)[key] = settings[key];
      }
    }

    setOverrides(newOverrides);
    setValues(newValues);
  }, [selectedGroupId, groups]);

  const toggleOverride = (key: keyof SearchSettings) => {
    setOverrides((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
        // Reset to system default
        setValues((v) => ({ ...v, [key]: SYSTEM_DEFAULTS[key] }));
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const updateValue = <K extends keyof SearchSettings>(key: K, val: SearchSettings[K]) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  };

  const handleSave = async () => {
    if (!selectedGroupId) return;
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      // Build payload with only overridden keys
      const payload: Record<string, unknown> = {};
      for (const key of SETTING_KEYS) {
        if (overrides.has(key)) {
          payload[key] = values[key];
        }
      }
      await axios.patch(`${API_BASE_URL}/groups/${selectedGroupId}`, {
        search_settings: Object.keys(payload).length > 0 ? payload : {},
      });
      setSuccess('Settings saved.');
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!selectedGroupId) return;
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      await axios.patch(`${API_BASE_URL}/groups/${selectedGroupId}`, {
        search_settings: {},
      });
      setOverrides(new Set());
      setValues({ ...SYSTEM_DEFAULTS });
      setSuccess('Settings reset to system defaults.');
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to reset settings');
    } finally {
      setSaving(false);
    }
  };

  const selectedGroup = groups.find((g) => g.id === selectedGroupId);

  if (loading) return <div className="admin-loading">Loading groups...</div>;

  return (
    <div className="admin-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}
      {success && (
        <div className="auth-success" style={{ background: '#d1fae5', color: '#065f46', padding: '8px 12px', borderRadius: '4px', marginBottom: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {success}
          <button className="auth-error-dismiss" onClick={() => setSuccess('')}>&times;</button>
        </div>
      )}

      <div className="admin-inline-form" style={{ marginBottom: '16px' }}>
        <select
          value={selectedGroupId}
          onChange={(e) => { setSelectedGroupId(e.target.value); setSuccess(''); }}
          className="admin-select"
        >
          <option value="">Select a group...</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}{g.is_default ? ' (Default)' : ''}
            </option>
          ))}
        </select>
      </div>

      {selectedGroup && (
        <div className="admin-group-settings">
          <p style={{ fontSize: '0.875rem', color: '#6b7280', marginBottom: '16px' }}>
            Override search and content settings for members of <strong>{selectedGroup.name}</strong>.
            Unchecked settings use system defaults.
          </p>

          {/* Search Settings */}
          <h4>Search Settings</h4>
          <div className="admin-settings-grid">
            {/* Dense Weight */}
            <SettingRow
              label={SETTING_LABELS.denseWeight}
              overridden={overrides.has('denseWeight')}
              onToggle={() => toggleOverride('denseWeight')}
            >
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={values.denseWeight}
                onChange={(e) => updateValue('denseWeight', parseFloat(e.target.value))}
                disabled={!overrides.has('denseWeight')}
                className="score-slider"
              />
              <div className="score-range-labels">
                <span>Keyword</span>
                <span>Semantic</span>
              </div>
            </SettingRow>

            {/* Rerank */}
            <BooleanSettingRow
              label={SETTING_LABELS.rerank}
              settingKey="rerank"
              overrides={overrides}
              values={values}
              onToggle={toggleOverride}
              onUpdate={updateValue}
            />

            {/* Recency Boost */}
            <BooleanSettingRow
              label={SETTING_LABELS.recencyBoost}
              settingKey="recencyBoost"
              overrides={overrides}
              values={values}
              onToggle={toggleOverride}
              onUpdate={updateValue}
            />

            {/* Recency Weight */}
            <SettingRow
              label={SETTING_LABELS.recencyWeight}
              overridden={overrides.has('recencyWeight')}
              onToggle={() => toggleOverride('recencyWeight')}
            >
              <input
                type="range"
                min={0.05}
                max={0.5}
                step={0.05}
                value={values.recencyWeight}
                onChange={(e) => updateValue('recencyWeight', parseFloat(e.target.value))}
                disabled={!overrides.has('recencyWeight')}
                className="score-slider"
              />
              <div className="score-range-labels">
                <span>Subtle ({values.recencyWeight})</span>
                <span>Strong</span>
              </div>
            </SettingRow>

            {/* Recency Scale Days */}
            <SettingRow
              label={SETTING_LABELS.recencyScaleDays}
              overridden={overrides.has('recencyScaleDays')}
              onToggle={() => toggleOverride('recencyScaleDays')}
            >
              <input
                type="range"
                min={180}
                max={1825}
                step={30}
                value={values.recencyScaleDays}
                onChange={(e) => updateValue('recencyScaleDays', parseInt(e.target.value, 10))}
                disabled={!overrides.has('recencyScaleDays')}
                className="score-slider"
              />
              <div className="score-range-labels">
                <span>6 months</span>
                <span>5 years ({values.recencyScaleDays}d)</span>
              </div>
            </SettingRow>

            {/* Keyword Boost */}
            <BooleanSettingRow
              label={SETTING_LABELS.keywordBoostShortQueries}
              settingKey="keywordBoostShortQueries"
              overrides={overrides}
              values={values}
              onToggle={toggleOverride}
              onUpdate={updateValue}
            />

            {/* Semantic Highlighting */}
            <BooleanSettingRow
              label={SETTING_LABELS.semanticHighlighting}
              settingKey="semanticHighlighting"
              overrides={overrides}
              values={values}
              onToggle={toggleOverride}
              onUpdate={updateValue}
            />

            {/* Auto Min Score */}
            <BooleanSettingRow
              label={SETTING_LABELS.autoMinScore}
              settingKey="autoMinScore"
              overrides={overrides}
              values={values}
              onToggle={toggleOverride}
              onUpdate={updateValue}
            />

            {/* Deduplicate */}
            <BooleanSettingRow
              label={SETTING_LABELS.deduplicate}
              settingKey="deduplicate"
              overrides={overrides}
              values={values}
              onToggle={toggleOverride}
              onUpdate={updateValue}
            />

            {/* Field Boost */}
            <BooleanSettingRow
              label={SETTING_LABELS.fieldBoost}
              settingKey="fieldBoost"
              overrides={overrides}
              values={values}
              onToggle={toggleOverride}
              onUpdate={updateValue}
            />

            {/* Field Boost Fields */}
            <SettingRow
              label={SETTING_LABELS.fieldBoostFields}
              overridden={overrides.has('fieldBoostFields')}
              onToggle={() => toggleOverride('fieldBoostFields')}
            >
              <div className="field-boost-fields">
                {BOOST_FIELD_OPTIONS.map(({ value, label }) => {
                  const isChecked = value in values.fieldBoostFields;
                  const weight = values.fieldBoostFields[value] ?? 0.5;
                  return (
                    <div key={value} className="field-boost-row">
                      <label className="section-type-checkbox">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          disabled={!overrides.has('fieldBoostFields')}
                          onChange={(e) => {
                            const next = { ...values.fieldBoostFields };
                            if (e.target.checked) {
                              next[value] = 0.5;
                            } else {
                              delete next[value];
                            }
                            updateValue('fieldBoostFields', next);
                          }}
                        />
                        <span>{label}</span>
                      </label>
                      {isChecked && (
                        <input
                          type="number"
                          min="0.1"
                          max="2.0"
                          step="0.1"
                          value={weight}
                          disabled={!overrides.has('fieldBoostFields')}
                          onChange={(e) => {
                            const v = parseFloat(e.target.value);
                            if (!isNaN(v)) {
                              updateValue('fieldBoostFields', {
                                ...values.fieldBoostFields,
                                [value]: v,
                              });
                            }
                          }}
                          className="field-boost-input"
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </SettingRow>
          </div>

          {/* Content Settings */}
          <h4>Content Settings</h4>
          <div className="admin-settings-grid">
            {/* Min Chunk Size */}
            <SettingRow
              label={SETTING_LABELS.minChunkSize}
              overridden={overrides.has('minChunkSize')}
              onToggle={() => toggleOverride('minChunkSize')}
            >
              <input
                type="range"
                min={0}
                max={1000}
                step={50}
                value={values.minChunkSize}
                onChange={(e) => updateValue('minChunkSize', parseInt(e.target.value, 10))}
                disabled={!overrides.has('minChunkSize')}
                className="score-slider"
              />
              <div className="score-range-labels">
                <span>0 (All)</span>
                <span>{values.minChunkSize} chars</span>
              </div>
            </SettingRow>

            {/* Section Types */}
            <SettingRow
              label={SETTING_LABELS.sectionTypes}
              overridden={overrides.has('sectionTypes')}
              onToggle={() => toggleOverride('sectionTypes')}
            >
              <div className="section-type-options">
                {SECTION_TYPE_OPTIONS.map(({ value, label }) => (
                  <label key={value} className="section-type-checkbox">
                    <input
                      type="checkbox"
                      checked={values.sectionTypes.includes(value)}
                      disabled={!overrides.has('sectionTypes')}
                      onChange={(e) => {
                        if (e.target.checked) {
                          updateValue('sectionTypes', [...values.sectionTypes, value]);
                        } else {
                          updateValue(
                            'sectionTypes',
                            values.sectionTypes.filter((s) => s !== value)
                          );
                        }
                      }}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </SettingRow>
          </div>

          {/* Actions */}
          <div className="admin-inline-form" style={{ marginTop: '16px', gap: '8px' }}>
            <button className="btn-sm" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save Settings'}
            </button>
            <button className="btn-sm btn-danger" onClick={handleReset} disabled={saving}>
              Reset to Defaults
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

/** A single setting row with an override checkbox. */
const SettingRow: React.FC<{
  label: string;
  overridden: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}> = ({ label, overridden, onToggle, children }) => (
  <div className={`admin-setting-row ${overridden ? '' : 'admin-setting-disabled'}`}>
    <label className="admin-setting-override">
      <input type="checkbox" checked={overridden} onChange={onToggle} />
      <span>{label}</span>
    </label>
    <div className="admin-setting-control">{children}</div>
  </div>
);

/** Shorthand for boolean toggle settings. */
const BooleanSettingRow: React.FC<{
  label: string;
  settingKey: keyof SearchSettings;
  overrides: Set<keyof SearchSettings>;
  values: Required<SearchSettings>;
  onToggle: (key: keyof SearchSettings) => void;
  onUpdate: <K extends keyof SearchSettings>(key: K, val: SearchSettings[K]) => void;
}> = ({ label, settingKey, overrides, values, onToggle, onUpdate }) => (
  <SettingRow
    label={label}
    overridden={overrides.has(settingKey)}
    onToggle={() => onToggle(settingKey)}
  >
    <label className="rerank-checkbox-label">
      <input
        type="checkbox"
        checked={values[settingKey] as boolean}
        onChange={(e) => onUpdate(settingKey, e.target.checked as any)}
        disabled={!overrides.has(settingKey)}
        className="rerank-checkbox"
      />
      <span>{(values[settingKey] as boolean) ? 'Enabled' : 'Disabled'}</span>
    </label>
  </SettingRow>
);

export default GroupSettingsManager;
