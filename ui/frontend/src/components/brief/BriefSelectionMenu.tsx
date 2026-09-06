// The small toolbar that appears over selected text in a brief.
//
// Selecting text offers actions rather than doing one thing: today that is
// "Comment", and further actions (e.g. researching a passage further) plug in
// by adding to the `actions` array — the menu lays out whatever it is given.

import React, { useEffect } from 'react';

export interface HighlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface BriefSelection {
  sectionId: string;
  text: string;
  // Viewport rect of the selection, used to place the menu above it.
  rect: { top: number; left: number; width: number };
  // One rect per line of the selection, so the passage can be kept visibly
  // marked after the browser's own selection loses focus (to the toolbar or
  // the comment box) and stops being drawn.
  rects: HighlightRect[];
}

export interface SelectionAction {
  key: string;
  label: string;
  icon?: React.ReactNode;
  title?: string;
  onRun: (selection: BriefSelection) => void;
}

const MENU_WIDTH = 132;

export const BriefSelectionMenu: React.FC<{
  selection: BriefSelection;
  actions: SelectionAction[];
  onClose: () => void;
}> = ({ selection, actions, onClose }) => {
  // Any scroll, resize or Escape dismisses it: the menu is anchored to a
  // viewport position, so it would otherwise drift away from its text.
  useEffect(() => {
    const dismiss = (): void => onClose();
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('scroll', dismiss, { passive: true });
    window.addEventListener('resize', dismiss);
    document.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('scroll', dismiss);
      window.removeEventListener('resize', dismiss);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  if (!actions.length) return null;

  // Centre over the selection, clamped so it stays on screen.
  const width = Math.max(MENU_WIDTH, actions.length * MENU_WIDTH);
  const left = Math.min(
    Math.max(8, selection.rect.left + selection.rect.width / 2 - width / 2),
    Math.max(8, window.innerWidth - width - 8),
  );

  return (
    <div
      className="brief-selection-menu"
      style={{ top: Math.max(8, selection.rect.top - 44), left }}
      // Keep the browser selection alive while the menu is used.
      onMouseDown={(e) => e.preventDefault()}
      role="toolbar"
      aria-label="Actions for the selected text"
    >
      {actions.map((action) => (
        <button
          key={action.key}
          className="brief-selection-action"
          title={action.title || action.label}
          onClick={() => action.onRun(selection)}
        >
          {action.icon}
          {action.label}
        </button>
      ))}
    </div>
  );
};


/**
 * Keeps the selected passage visibly marked while the toolbar or the comment
 * box is open. The browser stops painting its own selection once focus moves
 * away, which leaves the reader unsure what they are about to act on.
 */
export const BriefSelectionHighlight: React.FC<{ rects: HighlightRect[] }> = ({ rects }) => (
  <>
    {rects.map((r) => (
      <div
        // Geometry is unique per line and stable for a given selection.
        key={`${r.top}:${r.left}:${r.width}`}
        className="brief-selection-highlight"
        style={{ top: r.top, left: r.left, width: r.width, height: r.height }}
      />
    ))}
  </>
);
