import React, { useState, useEffect, useCallback, useRef } from 'react';

interface DigDeeperPopoverProps {
  containerRef: React.RefObject<HTMLDivElement | null>;
  onDrilldown: (selectedText: string) => void;
  disabled?: boolean;
}

const MIN_SELECTION_LENGTH = 10;

export const DigDeeperPopover: React.FC<DigDeeperPopoverProps> = ({
  containerRef,
  onDrilldown,
  disabled,
}) => {
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const [selectedText, setSelectedText] = useState('');
  const buttonRef = useRef<HTMLButtonElement>(null);

  const handleSelectionChange = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !containerRef.current) {
      setVisible(false);
      return;
    }

    const text = selection.toString().trim();
    if (text.length < MIN_SELECTION_LENGTH) {
      setVisible(false);
      return;
    }

    const range = selection.getRangeAt(0);
    if (!containerRef.current.contains(range.commonAncestorContainer)) {
      setVisible(false);
      return;
    }

    const rect = range.getBoundingClientRect();
    const containerRect = containerRef.current.getBoundingClientRect();

    setPosition({
      top: rect.bottom - containerRect.top + 4,
      left: rect.left - containerRect.left + rect.width / 2,
    });
    setSelectedText(text);
    setVisible(true);
  }, [containerRef]);

  useEffect(() => {
    document.addEventListener('selectionchange', handleSelectionChange);
    return () => document.removeEventListener('selectionchange', handleSelectionChange);
  }, [handleSelectionChange]);

  if (!visible || disabled) return null;

  return (
    <button
      ref={buttonRef}
      className="dig-deeper-popover"
      style={{
        position: 'absolute',
        top: position.top,
        left: position.left,
        transform: 'translateX(-50%)',
      }}
      onMouseDown={(e) => e.preventDefault()}
      onClick={(e) => {
        e.preventDefault();
        onDrilldown(selectedText);
        setVisible(false);
        window.getSelection()?.removeAllRanges();
      }}
    >
      Dig Deeper
    </button>
  );
};
