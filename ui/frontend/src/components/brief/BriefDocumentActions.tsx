import React, { useEffect, useRef, useState } from 'react';
import { BriefAskAi } from './BriefAskAi';
import { BriefAction, BriefActionMenu } from './BriefActionMenu';

function ActionButtons({ actions, primary = false, locked = false }: { actions: BriefAction[]; primary?: boolean; locked?: boolean }) {
  return <>{actions.map(({ label, icon: Icon, onSelect, disabled, title }) => (
    <button key={label} type="button" className={primary ? 'brief-regen-all brief-ai-primary' : 'brief-regen-all'} onClick={onSelect}
      disabled={locked || disabled} title={title}><Icon /> {label}</button>
  ))}</>;
}

// The seven expanded actions need about 1,305 CSS pixels, plus room for
// longer history counts. Measure the toolbar after side panels take their space.
const EXPANDED_ACTIONS_MIN_WIDTH = 1360;

export function useDocumentActionLayout() {
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [compact, setCompact] = useState(true);

  useEffect(() => {
    const toolbar = toolbarRef.current;
    if (!toolbar) return;
    const observer = new ResizeObserver(([entry]) => {
      setCompact(entry.contentRect.width < EXPANDED_ACTIONS_MIN_WIDTH);
    });
    observer.observe(toolbar);
    return () => observer.disconnect();
  }, []);

  return { toolbarRef, compact };
}

export function DocumentAiActions({ actions, disabled, compact }: {
  actions: BriefAction[]; disabled: boolean; compact: boolean;
}) {
  return compact
    ? <BriefAskAi label="Ask AI for the whole brief" buttonClass="brief-regen-all" actions={actions} disabled={disabled} />
    : <div className="brief-secondary-start" role="group" aria-label="Whole brief AI actions">
        <ActionButtons actions={actions} primary locked={disabled} />
      </div>;
}

export function BriefDocumentActions({ actions, compact }: { actions: BriefAction[]; compact: boolean }) {
  if (!actions.length) return null;
  if (compact) return <BriefActionMenu label="More actions" buttonText="More"
    buttonClass="brief-regen-all brief-more-actions" actions={actions} />;
  return <div className="brief-expanded-actions">
    <div className="brief-secondary-start"><ActionButtons actions={actions.filter(action => action.align !== 'end')} /></div>
    <div className="brief-secondary-end" role="group" aria-label="Document output and history">
      <ActionButtons actions={actions.filter(action => action.align === 'end')} />
    </div>
  </div>;
}
