import React from 'react';
import { render, screen } from '@testing-library/react';
import { BriefSectionFrame } from '../components/brief/BriefSectionFrame';

test('starting and finishing research keep the focused section at its viewport position', () => {
  const frame = (running: boolean) => <BriefSectionFrame researching={running}>
    <input aria-label="Heading" />
  </BriefSectionFrame>;
  const scroll = jest.spyOn(window, 'scrollBy').mockImplementation(() => {});
  const view = render(frame(false));
  const heading = screen.getByRole('textbox');
  const section = heading.closest('section')!;
  const rect = jest.spyOn(section, 'getBoundingClientRect');
  const bounds = (top: number) => ({ top, bottom: top + 100 } as DOMRect);
  try {
    heading.focus();
    rect.mockReturnValueOnce(bounds(350)).mockReturnValueOnce(bounds(20));
    view.rerender(frame(true));
    expect(scroll).toHaveBeenLastCalledWith({ top: -330, behavior: 'auto' });
    rect.mockReturnValueOnce(bounds(350)).mockReturnValueOnce(bounds(400));
    view.rerender(frame(false));
    expect(scroll).toHaveBeenLastCalledWith({ top: 50, behavior: 'auto' });
    heading.blur();
    view.rerender(frame(true));
    expect(scroll).toHaveBeenCalledTimes(2);
    heading.focus();
    rect.mockReturnValue(bounds(-1000));
    view.rerender(frame(false));
    expect(scroll).toHaveBeenCalledTimes(2);
  } finally {
    scroll.mockRestore();
  }
});
