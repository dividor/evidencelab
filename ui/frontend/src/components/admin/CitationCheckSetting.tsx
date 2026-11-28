import React from 'react';

interface Props {
  id: string;
  value?: boolean;
  defaultEnabled?: boolean;
  onChange: (value: boolean | undefined) => void;
}

export const CitationCheckSetting: React.FC<Props> = ({ id, value, defaultEnabled, onChange }) => (
  <div className="search-settings-group">
    <label className="search-settings-label" htmlFor={id}>Automatic citation check</label>
    <select id={id} className="filter-select" value={value === undefined ? '' : String(value)} onChange={event => {
      const selected = event.currentTarget.value;
      onChange(selected ? selected === 'true' : undefined);
    }}>
      <option value="">{defaultEnabled === undefined ? 'Use site default' : `${defaultEnabled ? 'On' : 'Off'} (default)`}</option>
      <option value="true">On</option>
      <option value="false">Off</option>
    </select>
  </div>
);
