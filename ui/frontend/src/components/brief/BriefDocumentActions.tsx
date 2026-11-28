import React, { useEffect, useState } from 'react';
import { BriefAskAi } from './BriefAskAi';
import { BriefAction, BriefActionMenu } from './BriefActionMenu';

function ActionButtons({ actions, primary = false, locked = false }: { actions: BriefAction[]; primary?: boolean; locked?: boolean }) {
  return <>{actions.map(({ label, icon: Icon, onSelect, disabled, title }) => (
    <button key={label} type="button" className={primary ? 'brief-regen-all brief-ai-primary' : 'brief-regen-all'} onClick={onSelect}
      disabled={locked || disabled} title={title}><Icon /> {label}</button>
  ))}</>;
}

function useCompactActions() {
  const [compact, setCompact] = useState(() => window.innerWidth <= 1024);
  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 1024);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  return compact;
}

export function DocumentAiActions({ actions, disabled }: { actions: BriefAction[]; disabled: boolean }) {
  return useCompactActions()
    ? <BriefAskAi label="Ask AI for the whole brief" buttonClass="brief-regen-all" actions={actions} disabled={disabled} />
    : <div className="brief-secondary-start" role="group" aria-label="Whole brief AI actions">
        <ActionButtons actions={actions} primary locked={disabled} />
      </div>;
}

export function BriefDocumentActions({ actions }: { actions: BriefAction[] }) {
  const compact = useCompactActions();
  if (!actions.length) return null;
  if (compact) return <BriefActionMenu label="More actions" buttonText="More Actions"
    buttonClass="brief-regen-all brief-more-actions" actions={actions} />;
  return <div className="brief-expanded-actions">
    <div className="brief-secondary-start"><ActionButtons actions={actions.filter(action => action.align !== 'end')} /></div>
    <div className="brief-secondary-end" role="group" aria-label="Document output and history">
      <ActionButtons actions={actions.filter(action => action.align === 'end')} />
    </div>
  </div>;
}
