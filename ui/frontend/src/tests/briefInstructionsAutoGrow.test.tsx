import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { BriefSeed } from '../components/brief/BriefSeed';
import { PROMPT_MAX_CHARS } from '../components/brief/briefTypes';
import type { UseBriefReturn } from '../components/brief/useBrief';

// The Brief instructions field grows with its content so a long prompt stays
// readable, and Enter inserts a line break rather than submitting anything.

const makeBrief = (instructions: string): UseBriefReturn =>
  ({
    query: 'Child wasting',
    setQuery: jest.fn(),
    instructions,
    setInstructions: jest.fn(),
    numHeadings: 5,
    setNumHeadings: jest.fn(),
    targetWords: null,
    setTargetWords: jest.fn(),
    generateOutline: jest.fn(),
    startManual: jest.fn(),
    outlineLoading: false,
    error: null,
    setHistoryOpen: jest.fn(),
    history: [],
    generatingActivity: [],
  }) as unknown as UseBriefReturn;

const LINE = 20;
const originalScrollHeight = Object.getOwnPropertyDescriptor(
  Element.prototype,
  'scrollHeight'
) as PropertyDescriptor;

beforeAll(() => {
  Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return this.value.split('\n').length * LINE;
    },
  });
});

afterAll(() => {
  delete (HTMLTextAreaElement.prototype as { scrollHeight?: number }).scrollHeight;
  Object.defineProperty(Element.prototype, 'scrollHeight', originalScrollHeight);
});

const instructionsField = () => screen.getByLabelText(/^Instructions/) as HTMLTextAreaElement;

describe('BriefSeed instructions field', () => {
  test('is an auto-growing textarea that keeps the prompt length limit', () => {
    const { rerender } = render(<BriefSeed brief={makeBrief('focus on East Africa')} />);
    const field = instructionsField();
    expect(field.tagName).toBe('TEXTAREA');
    expect(field.maxLength).toBe(PROMPT_MAX_CHARS);
    expect(field.style.height).toBe(`${LINE}px`);

    rerender(<BriefSeed brief={makeBrief('focus on East Africa\nprioritise RCTs\nsince 2018')} />);
    expect(instructionsField().style.height).toBe(`${3 * LINE}px`);
  });

  test('Enter does not trigger outline generation', () => {
    const brief = makeBrief('focus on East Africa');
    render(<BriefSeed brief={brief} />);
    const keyDown = fireEvent.keyDown(instructionsField(), { key: 'Enter' });
    expect(keyDown).toBe(true); // not prevented, so the browser inserts a line break
    expect(brief.generateOutline).not.toHaveBeenCalled();
  });
});
