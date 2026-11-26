import React, { useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { BriefLengthControl } from '../brief/BriefLengthControl';
import { GroupPromptEditor } from './GroupPromptEditor';

interface Props {
  targetWords: number | null;
  onTargetWordsChange: (value: number | null) => void;
  sectionPrompt?: string;
  onSectionPromptChange: (value: string | undefined) => void;
}

export const BriefGroupSection: React.FC<Props> = ({
  targetWords, onTargetWordsChange, sectionPrompt, onSectionPromptChange,
}) => {
  const [defaultPrompt, setDefaultPrompt] = useState('');
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios.get<{ sectionPrompt: string }>(`${API_BASE_URL}/groups/brief-defaults`)
      .then(({ data }) => { if (!cancelled) setDefaultPrompt(data.sectionPrompt); })
      .catch(() => { if (!cancelled) setLoadError(true); });
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <label className="rerank-checkbox-label" htmlFor="group-brief-target-words">
        <span>Default section length</span>
        <span className="rerank-tooltip"
          title="The section length target new briefs start with, in words per section. Authors can change it per brief and per section. Sections that overshoot the target by more than the configured tolerance are condensed automatically.">
          ⓘ
        </span>
      </label>
      <BriefLengthControl id="group-brief-target-words" value={targetWords} onChange={onTargetWordsChange} />
      {loadError && <p role="alert">Could not load the default Brief prompt.</p>}
      <GroupPromptEditor id="group-brief-section-prompt" label="Section prompt"
        help="Guide the writing of individual sections. The target length and outline still apply."
        value={sectionPrompt} defaultPrompt={defaultPrompt} disabled={!defaultPrompt}
        onChange={onSectionPromptChange} />
    </>
  );
};
