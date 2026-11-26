import React, { useEffect, useId, useRef, useState } from 'react';
import { IconChevronDown, IconSparkle } from './BriefIcons';

interface BriefAiAction {
  label: string;
  icon: React.ComponentType;
  onSelect: () => void;
  title?: string;
}

interface BriefAskAiProps {
  label: string;
  buttonClass: string;
  actions: BriefAiAction[];
  disabled?: boolean;
}

export const BriefAskAi: React.FC<BriefAskAiProps> = ({ label, buttonClass, actions, disabled }) => {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const optionsId = useId();

  useEffect(() => {
    if (disabled) {
      setOpen(false);
      return;
    }
    if (!open) return;

    const dismissOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !container.current?.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', dismissOutside);
    return () => document.removeEventListener('pointerdown', dismissOutside);
  }, [disabled, open]);

  const closeAndFocus = () => {
    setOpen(false);
    trigger.current?.focus();
  };

  return (
    <div
      className="brief-ask-ai"
      ref={container}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (open && event.key === 'Escape') {
          event.stopPropagation();
          closeAndFocus();
        }
      }}
    >
      <button
        type="button"
        className={buttonClass}
        ref={trigger}
        aria-label={label}
        aria-controls={optionsId}
        aria-expanded={open && !disabled}
        disabled={disabled}
        onClick={() => {
          trigger.current?.focus();
          setOpen(!open);
        }}
      >
        <IconSparkle /> Ask AI <IconChevronDown />
      </button>
      <div id={optionsId} className="brief-ai-options" hidden={!open || disabled}>
        {actions.map(({ label: actionLabel, icon: Icon, title, onSelect }) => (
          <button
            key={actionLabel}
            type="button"
            className="brief-ai-option"
            title={title}
            onClick={() => {
              closeAndFocus();
              onSelect();
            }}
          >
            <Icon /> {actionLabel}
          </button>
        ))}
      </div>
    </div>
  );
};
