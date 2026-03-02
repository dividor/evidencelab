import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { GROUP_SETTINGS_UPDATED_EVENT } from '../../hooks/useGroupDefaults';
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

const GroupSettingsManager: React.FC = () => {
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Which keys are overridden vs using system default
  const [overrides, setOverrides] = useState<Set<keyof SearchSettings>>(new Set());
  // Current values for all settings (overridden or system default)
  const [values, setValues] = useState<Required<SearchSettings>>({ ...SYSTEM_DEFAULTS });

  // Collapsible sections — both open by default
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(
    new Set(['search_settings', 'content_settings'])
  );

  const toggleSection = (key: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

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

  /** Update a value and mark it as overridden. */
  const update = <K extends keyof SearchSettings>(key: K, val: SearchSettings[K]) => {
    setValues((prev) => ({ ...prev, [key]: val }));
    setOverrides((prev) => new Set(prev).add(key));
  };

  const handleSave = async () => {
    if (!selectedGroupId) return;
    setSaving(true);
    setError('');
    setSuccess('');
    try {
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
      window.dispatchEvent(new Event(GROUP_SETTINGS_UPDATED_EVENT));
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
            Configure default search and content settings for <strong>{selectedGroup.name}</strong> members.
            Changed settings are saved per-group; users can still override via URL parameters.
          </p>

          {/* Search Settings — matches SearchSettingsPanel layout */}
          <div className="filter-section">
            <div className="filter-section-header" onClick={() => toggleSection('search_settings')}>
              <span className="filter-section-toggle">
                {collapsedSections.has('search_settings') ? '▼' : '▶'}
              </span>
              <span className="filter-section-title">Search Settings</span>
            </div>
            {collapsedSections.has('search_settings') && (
              <div className="filter-section-content">
                {/* Search Mode (denseWeight) */}
                <div className="search-settings-group">
                  <label className="search-settings-label">Search Mode</label>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.1}
                    value={values.denseWeight}
                    onChange={(e) => update('denseWeight', parseFloat(e.target.value))}
                    className="score-slider"
                    style={{
                      background: `linear-gradient(to right,
                        #93c5fd ${values.denseWeight * 100}%,
                        #0066cc ${values.denseWeight * 100}%)`,
                    }}
                  />
                  <div className="score-range-labels">
                    <span>Keyword</span>
                    <span>Semantic</span>
                  </div>
                </div>

                {/* Keyword Boost Short Queries */}
                <label className="rerank-checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.keywordBoostShortQueries}
                    onChange={(e) => update('keywordBoostShortQueries', e.target.checked)}
                    className="rerank-checkbox"
                  />
                  <span>Keyword Boost Short Queries</span>
                  <span
                    className="rerank-tooltip"
                    title="When enabled, queries with 2 words or less automatically use lower semantic weight for better keyword matching."
                  >
                    ⓘ
                  </span>
                </label>

                {/* Semantic Highlighting */}
                <label className="rerank-checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.semanticHighlighting}
                    onChange={(e) => update('semanticHighlighting', e.target.checked)}
                    className="rerank-checkbox"
                  />
                  <span>Semantic Highlighting</span>
                  <span
                    className="rerank-tooltip"
                    title="Use advanced AI to highlight semantically relevant phrases in search results."
                  >
                    ⓘ
                  </span>
                </label>

                {/* Auto Min Score */}
                <label className="rerank-checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.autoMinScore}
                    onChange={(e) => update('autoMinScore', e.target.checked)}
                    className="rerank-checkbox"
                  />
                  <span>Auto Min Score</span>
                  <span
                    className="rerank-tooltip"
                    title="Automatically determine the minimum relevance score threshold."
                  >
                    ⓘ
                  </span>
                </label>

                {/* Enable Reranker */}
                <label className="rerank-checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.rerank}
                    onChange={(e) => update('rerank', e.target.checked)}
                    className="rerank-checkbox"
                  />
                  <span>Enable Reranker</span>
                  <span
                    className="rerank-tooltip"
                    title="Use a cross-encoder model to rerank results for better relevance. May be slower."
                  >
                    ⓘ
                  </span>
                </label>

                {/* Boost Recent Reports + sub-sliders */}
                <label className="rerank-checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.recencyBoost}
                    onChange={(e) => update('recencyBoost', e.target.checked)}
                    className="rerank-checkbox"
                  />
                  <span>Boost Recent Reports</span>
                  <span
                    className="rerank-tooltip"
                    title="Prioritize recently published reports in search results. Current year reports get maximum boost."
                  >
                    ⓘ
                  </span>
                </label>

                {values.recencyBoost && (
                  <>
                    <div className="recency-slider-group">
                      <label className="recency-slider-label">Recency Weight</label>
                      <input
                        type="range"
                        min="0.05"
                        max="0.5"
                        step="0.05"
                        value={values.recencyWeight}
                        onChange={(e) => update('recencyWeight', parseFloat(e.target.value))}
                        className="score-slider recency-weight-slider"
                      />
                      <div className="score-range-labels">
                        <span>Subtle</span>
                        <span>Strong</span>
                      </div>
                    </div>

                    <div className="recency-slider-group">
                      <label className="recency-slider-label">Decay Scale</label>
                      <input
                        type="range"
                        min="180"
                        max="1825"
                        step="30"
                        value={values.recencyScaleDays}
                        onChange={(e) => update('recencyScaleDays', parseInt(e.target.value, 10))}
                        className="score-slider recency-scale-slider"
                      />
                      <div className="score-range-labels">
                        <span>6 months</span>
                        <span>5 years</span>
                      </div>
                    </div>
                  </>
                )}

                {/* Deduplicate */}
                <label className="rerank-checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.deduplicate}
                    onChange={(e) => update('deduplicate', e.target.checked)}
                    className="rerank-checkbox"
                  />
                  <span>Deduplicate</span>
                  <span
                    className="rerank-tooltip"
                    title="Deduplicate content found in multiple reports"
                  >
                    ⓘ
                  </span>
                </label>

                {/* Field Level Boosting */}
                <label className="rerank-checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.fieldBoost}
                    onChange={(e) => update('fieldBoost', e.target.checked)}
                    className="rerank-checkbox"
                  />
                  <span>Field Level Boosting</span>
                  <span
                    className="rerank-tooltip"
                    title="Boost fields such as organization and country if configured for this data source"
                  >
                    ⓘ
                  </span>
                </label>
                {values.fieldBoost && (
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
                              onChange={(e) => {
                                const next = { ...values.fieldBoostFields };
                                if (e.target.checked) {
                                  next[value] = 0.5;
                                } else {
                                  delete next[value];
                                }
                                update('fieldBoostFields', next);
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
                              onChange={(e) => {
                                const v = parseFloat(e.target.value);
                                if (!isNaN(v)) {
                                  update('fieldBoostFields', {
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
                )}
              </div>
            )}
          </div>

          {/* Content Settings — matches SearchSettingsPanel layout */}
          <div className="filter-section">
            <div className="filter-section-header" onClick={() => toggleSection('content_settings')}>
              <span className="filter-section-toggle">
                {collapsedSections.has('content_settings') ? '▼' : '▶'}
              </span>
              <span className="filter-section-title">Content Settings</span>
            </div>
            {collapsedSections.has('content_settings') && (
              <div className="filter-section-content">
                {/* Min Chunk Size */}
                <div
                  className="search-settings-group"
                  style={{ marginBottom: '15px', paddingBottom: '15px', borderBottom: '1px solid #e5e7eb' }}
                >
                  <label
                    className="search-settings-label"
                    title="Filter out chunks with fewer characters than this value. Default is 100 chars."
                  >
                    Min Chunk Size: {values.minChunkSize} chars
                    <span
                      className="rerank-tooltip"
                      title="Filter out chunks with fewer characters than this value. Helps remove noise like headers, footers, and fragmented sentences."
                    >
                      ⓘ
                    </span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="1000"
                    step="50"
                    value={values.minChunkSize}
                    onChange={(e) => update('minChunkSize', parseInt(e.target.value, 10))}
                    className="score-slider"
                    style={{
                      background: `linear-gradient(to right,
                        #93c5fd ${(values.minChunkSize / 1000) * 100}%,
                        #e5e7eb ${(values.minChunkSize / 1000) * 100}%)`,
                    }}
                  />
                  <div className="score-range-labels">
                    <span>0 (All)</span>
                    <span>1000</span>
                  </div>
                </div>

                {/* Section Types with Select All */}
                <div className="content-type-label">
                  <span>Section Type</span>
                  <span
                    className="rerank-tooltip"
                    title="Filter by document section type. Leave all unchecked to include all sections."
                  >
                    ⓘ
                  </span>
                </div>
                <label className="section-type-checkbox" style={{ marginBottom: '0.5em', fontWeight: '600' }}>
                  <input
                    type="checkbox"
                    checked={values.sectionTypes.length === SECTION_TYPE_OPTIONS.length}
                    ref={(el) => {
                      if (el) {
                        el.indeterminate =
                          values.sectionTypes.length > 0 &&
                          values.sectionTypes.length < SECTION_TYPE_OPTIONS.length;
                      }
                    }}
                    onChange={(e) => {
                      if (e.target.checked) {
                        update('sectionTypes', SECTION_TYPE_OPTIONS.map((item) => item.value));
                      } else {
                        update('sectionTypes', []);
                      }
                    }}
                  />
                  <span>Select All</span>
                </label>
                <div className="section-type-options">
                  {SECTION_TYPE_OPTIONS.map(({ value, label }) => (
                    <label key={value} className="section-type-checkbox">
                      <input
                        type="checkbox"
                        checked={values.sectionTypes.includes(value)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            update('sectionTypes', [...values.sectionTypes, value]);
                          } else {
                            update(
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
              </div>
            )}
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

export default GroupSettingsManager;
