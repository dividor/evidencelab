import React, { useEffect, useId, useRef, useState } from 'react';
import { IconChevronDown } from './BriefIcons';

export interface BriefAction {
  label: string;
  icon: React.ComponentType;
  onSelect: () => void;
  title?: string;
  disabled?: boolean;
  align?: 'end';
}

interface BriefActionMenuProps {
  label: string;
  buttonClass: string;
  buttonText: string;
  icon?: React.ComponentType;
  actions: BriefAction[];
  disabled?: boolean;
}

export const BriefActionMenu: React.FC<BriefActionMenuProps> = ({ label, buttonClass, buttonText, icon: TriggerIcon, actions, disabled }) => {
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
      className="brief-action-menu"
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
        title={label}
        aria-controls={optionsId}
        aria-expanded={open && !disabled}
        disabled={disabled}
        onClick={() => {
          trigger.current?.focus();
          setOpen(!open);
        }}
      >
        {TriggerIcon && <TriggerIcon />} {buttonText} <IconChevronDown />
      </button>
      <div id={optionsId} className="brief-ai-options" hidden={!open || disabled}>
        {actions.map(({ label: actionLabel, icon: Icon, title, onSelect, disabled: actionDisabled }) => (
          <button
            key={actionLabel}
            type="button"
            className="brief-ai-option"
            title={title}
            disabled={actionDisabled}
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
