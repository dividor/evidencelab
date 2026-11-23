import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { AutoGrowTextarea, AUTO_GROW_MAX_HEIGHT } from '../components/AutoGrowTextarea';

// jsdom does no layout, so scrollHeight is derived from the number of lines:
// 20px per line plus 20px of padding.
const LINE = 20;
const PADDING = 20;
const originalScrollHeight = Object.getOwnPropertyDescriptor(
  Element.prototype,
  'scrollHeight'
) as PropertyDescriptor;

beforeAll(() => {
  Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return this.value.split('\n').length * LINE + PADDING;
    },
  });
});

afterAll(() => {
  delete (HTMLTextAreaElement.prototype as { scrollHeight?: number }).scrollHeight;
  Object.defineProperty(Element.prototype, 'scrollHeight', originalScrollHeight);
});

const textarea = () => screen.getByRole('textbox') as HTMLTextAreaElement;

describe('AutoGrowTextarea sizing', () => {
  test('fits one line on mount and grows when the value gains lines', () => {
    const { rerender } = render(<AutoGrowTextarea value="one" onChange={() => undefined} />);
    expect(textarea().style.height).toBe(`${LINE + PADDING}px`);
    expect(textarea().style.overflowY).toBe('hidden');

    rerender(<AutoGrowTextarea value={'one\ntwo\nthree'} onChange={() => undefined} />);
    expect(textarea().style.height).toBe(`${3 * LINE + PADDING}px`);
    expect(textarea().style.overflowY).toBe('hidden');
  });

  test('shrinks again when lines are removed', () => {
    const { rerender } = render(
      <AutoGrowTextarea value={'one\ntwo\nthree'} onChange={() => undefined} />
    );
    rerender(<AutoGrowTextarea value="one" onChange={() => undefined} />);
    expect(textarea().style.height).toBe(`${LINE + PADDING}px`);
  });

  test('stops at maxHeight and scrolls inside instead', () => {
    render(
      <AutoGrowTextarea
        value={'1\n2\n3\n4\n5\n6'}
        maxHeight={3 * LINE}
        onChange={() => undefined}
      />
    );
    expect(textarea().style.height).toBe(`${3 * LINE}px`);
    expect(textarea().style.overflowY).toBe('auto');
  });

  test('uses the shared default max height when none is given', () => {
    const lines = Array.from({ length: 40 }, (_, i) => `line ${i}`).join('\n');
    render(<AutoGrowTextarea value={lines} onChange={() => undefined} />);
    expect(textarea().style.height).toBe(`${AUTO_GROW_MAX_HEIGHT}px`);
  });

  test('passes through native textarea props', () => {
    render(
      <AutoGrowTextarea
        value=""
        onChange={() => undefined}
        rows={2}
        maxLength={10}
        placeholder="Type here"
        className="my-field"
      />
    );
    const el = screen.getByPlaceholderText('Type here') as HTMLTextAreaElement;
    expect(el.tagName).toBe('TEXTAREA');
    expect(el.rows).toBe(2);
    expect(el.maxLength).toBe(10);
    expect(el.className).toBe('my-field');
  });
});

describe('AutoGrowTextarea Enter handling', () => {
  const renderInForm = (props: Partial<React.ComponentProps<typeof AutoGrowTextarea>> = {}) => {
    const onSubmit = jest.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <AutoGrowTextarea value="query" onChange={() => undefined} {...props} />
      </form>
    );
    return onSubmit;
  };

  test('Enter submits the form when submitOnEnter is set', () => {
    const onSubmit = renderInForm({ submitOnEnter: true });
    fireEvent.keyDown(textarea(), { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  test('Shift+Enter does not submit, so it inserts a line break', () => {
    const onSubmit = renderInForm({ submitOnEnter: true });
    fireEvent.keyDown(textarea(), { key: 'Enter', shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test('Enter does nothing special without submitOnEnter', () => {
    const onSubmit = renderInForm();
    fireEvent.keyDown(textarea(), { key: 'Enter' });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test('Enter during IME composition does not submit', () => {
    const onSubmit = renderInForm({ submitOnEnter: true });
    fireEvent.keyDown(textarea(), { key: 'Enter', isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test('a caller onKeyDown still runs and can cancel the submit', () => {
    const onKeyDown = jest.fn((e: React.KeyboardEvent) => e.preventDefault());
    const onSubmit = renderInForm({ submitOnEnter: true, onKeyDown });
    fireEvent.keyDown(textarea(), { key: 'Enter' });
    expect(onKeyDown).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
