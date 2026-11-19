import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { DataUrlImage, isImageDataUrl } from '../components/admin/RatingsManager';

jest.mock('axios');

const JPEG = 'data:image/jpeg;base64,/9j/4AAQSkZJRg==';

describe('feedback screenshots in the admin Ratings screen', () => {
  test.each([
    ['data:image/jpeg;base64,abc', true],
    ['data:image/png;base64,abc', true],
    ['data:image/svg+xml;base64,PHN2Zz4=', false],
    ['data:text/html;base64,PHA+', false],
  ])('treats %s as an image: %s', (value, expected) => {
    expect(isImageDataUrl(value)).toBe(expected);
  });

  test('opens the full-size view inside the page, not in a new tab', () => {
    const open = jest.spyOn(window, 'open').mockImplementation(() => null);
    render(<DataUrlImage src={JPEG} alt="screenshot" />);

    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByAltText('screenshot'));

    expect(screen.getByRole('dialog', { name: 'screenshot (full size)' })).toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('dialog'));
    expect(screen.queryByRole('dialog')).toBeNull();
    open.mockRestore();
  });
});
