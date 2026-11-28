import React from 'react';
import { IconSparkle } from './BriefIcons';
import { BriefActionMenu, BriefAction } from './BriefActionMenu';

export const BriefAskAi: React.FC<{
  label: string; buttonClass: string; actions: BriefAction[]; disabled?: boolean;
}> = props => <BriefActionMenu {...props} buttonClass={`${props.buttonClass} brief-ai-primary`}
  buttonText="Ask AI" icon={IconSparkle} />;
