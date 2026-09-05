import React, { useCallback, useRef, useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { useCloseOnOutsideClick } from '../hooks/useCloseOnOutsideClick';

interface HarnessProps {
  initiallyOpen?: boolean;
  onClose?: () => void;
}

const Harness = ({ initiallyOpen = true, onClose }: HarnessProps) => {
  const [open, setOpen] = useState(initiallyOpen);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => {
    setOpen(false);
    onClose?.();
  }, [onClose]);
  useCloseOnOutsideClick(ref, open, close);
  return (
    <div>
      <button>outside</button>
      <div ref={ref}>
        <button>trigger</button>
        {open && <button>inside</button>}
      </div>
    </div>
  );
};

describe('useCloseOnOutsideClick', () => {
  it('closes on mouse-down outside the container', () => {
    const onClose = jest.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.mouseDown(screen.getByText('outside'));
    expect(screen.queryByText('inside')).not.toBeInTheDocument();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('stays open on mouse-down inside the container', () => {
    const onClose = jest.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.mouseDown(screen.getByText('inside'));
    fireEvent.mouseDown(screen.getByText('trigger'));
    expect(screen.getByText('inside')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on touch-start outside the container', () => {
    render(<Harness />);
    fireEvent.touchStart(document.body);
    expect(screen.queryByText('inside')).not.toBeInTheDocument();
  });

  it('closes on Escape', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByText('inside')).not.toBeInTheDocument();
  });

  it('ignores other keys', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(screen.getByText('inside')).toBeInTheDocument();
  });

  it('does not listen while closed', () => {
    const onClose = jest.fn();
    render(<Harness initiallyOpen={false} onClose={onClose} />);
    fireEvent.mouseDown(document.body);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('removes its listeners on unmount', () => {
    const removeSpy = jest.spyOn(document, 'removeEventListener');
    const { unmount } = render(<Harness />);
    unmount();
    const removed = removeSpy.mock.calls.map(([type]) => type);
    expect(removed).toEqual(expect.arrayContaining(['mousedown', 'touchstart', 'keydown']));
    removeSpy.mockRestore();
  });
});
