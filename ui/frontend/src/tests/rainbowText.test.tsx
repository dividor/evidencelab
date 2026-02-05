import React from 'react';
import { render } from '@testing-library/react';

import { RainbowText } from '../components/RainbowText';

describe('RainbowText', () => {
  test('renders one span per character', () => {
    const { container } = render(<RainbowText text="A B" />);

    const spans = container.querySelectorAll('span.wave-char');
    expect(spans).toHaveLength(3);
    expect(spans[1].textContent).toBe('\u00A0');
  });
});
