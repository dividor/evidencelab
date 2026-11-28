import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { GroupPromptEditor } from './GroupPromptEditor';

interface Props {
  value?: string;
  defaultGroupPrompt?: string | null;
  isDefaultGroup: boolean;
  onChange: (value: string | undefined) => void;
}

export const SearchSummaryGroupPrompt: React.FC<Props> = ({ value, defaultGroupPrompt, isDefaultGroup, onChange }) => {
  const [sitePrompt, setSitePrompt] = useState('');
  const [loadError, setLoadError] = useState(false);
  const inheritedPrompt = isDefaultGroup ? '' : defaultGroupPrompt?.trim();

  useEffect(() => {
    if (inheritedPrompt) return;
    let cancelled = false;
    axios.get<{ systemPrompt: string }>(`${API_BASE_URL}/groups/summary-defaults`)
      .then(({ data }) => { if (!cancelled) setSitePrompt(data.systemPrompt); })
      .catch(() => { if (!cancelled) setLoadError(true); });
    return () => { cancelled = true; };
  }, [inheritedPrompt]);

  const defaultPrompt = inheritedPrompt || sitePrompt;
  return (
    <>
      {loadError && !defaultPrompt && <p role="alert">Could not load the default summary prompt.</p>}
      <GroupPromptEditor id="group-search-summary-prompt" label="Search AI Summary prompt"
        help={inheritedPrompt
          ? 'Guide summaries of search results for this group. Reset to use the Default group’s prompt.'
          : 'Guide summaries of search results for this group. Reset to use the site prompt.'}
        value={value} defaultPrompt={defaultPrompt} disabled={!defaultPrompt}
        onChange={onChange} />
    </>
  );
};
