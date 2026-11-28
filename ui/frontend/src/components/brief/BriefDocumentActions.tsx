import React, { useEffect, useState } from 'react';
import { BriefAction, BriefActionMenu } from './BriefActionMenu';

function ActionButtons({ actions }: { actions: BriefAction[] }) {
  return <>{actions.map(({ label, icon: Icon, onSelect, disabled, title }) => (
    <button key={label} type="button" className="brief-regen-all" onClick={onSelect}
      disabled={disabled} title={title}><Icon /> {label}</button>
  ))}</>;
}

/** Keep secondary document actions visible when the viewport has room. */
export function BriefDocumentActions({ actions }: { actions: BriefAction[] }) {
  const [compact, setCompact] = useState(() => window.innerWidth <= 1024);
  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 1024);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
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
