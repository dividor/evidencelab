import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { BriefLengthControl } from '../components/brief/BriefLengthControl';
import { BRIEF_LENGTH } from '../components/brief/briefLength';

const LENGTH = 'Length';
const CUSTOM_INPUT = 'Target words per section';

describe('BriefLengthControl', () => {
  test('offers no target, the configured presets and custom', () => {
    render(<BriefLengthControl value={null} onChange={jest.fn()} ariaLabel={LENGTH} />);
    const options = Array.from(screen.getByRole('combobox', { name: LENGTH }).querySelectorAll('option')).map(
      (o) => o.textContent,
    );
    expect(options).toEqual([
      'No target (model decides)',
      ...BRIEF_LENGTH.presets.map((p) => `${p.label} (~${p.words} words)`),
      'Custom…',
    ]);
  });

  test('picking a preset reports its word count; picking no target reports null', () => {
    const onChange = jest.fn();
    render(<BriefLengthControl value={null} onChange={onChange} ariaLabel={LENGTH} />);
    fireEvent.change(screen.getByRole('combobox', { name: LENGTH }), { target: { value: '150' } });
    expect(onChange).toHaveBeenLastCalledWith(150);
    fireEvent.change(screen.getByRole('combobox', { name: LENGTH }), { target: { value: 'none' } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  test('custom shows a number input and clamps to the configured range on commit', () => {
    const onChange = jest.fn();
    render(<BriefLengthControl value={null} onChange={onChange} ariaLabel={LENGTH} />);
    fireEvent.change(screen.getByRole('combobox', { name: LENGTH }), { target: { value: 'custom' } });
    const input = screen.getByRole('spinbutton', { name: CUSTOM_INPUT });
    fireEvent.change(input, { target: { value: '275' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(275);
    fireEvent.change(input, { target: { value: '999999' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith(BRIEF_LENGTH.max);
  });

  test('a non-preset value opens in custom mode showing that value', () => {
    render(<BriefLengthControl value={275} onChange={jest.fn()} ariaLabel={LENGTH} />);
    expect(screen.getByRole('combobox', { name: LENGTH })).toHaveValue('custom');
    expect(screen.getByRole('spinbutton', { name: CUSTOM_INPUT })).toHaveValue(275);
  });

  test('per-section use offers an inherit option that reports null', () => {
    const onChange = jest.fn();
    render(
      <BriefLengthControl value={350} onChange={onChange} inheritLabel="Use brief target — Short (~150 words)" ariaLabel={LENGTH} />,
    );
    expect(screen.getByRole('combobox', { name: LENGTH })).toHaveValue('350');
    fireEvent.change(screen.getByRole('combobox', { name: LENGTH }), { target: { value: 'inherit' } });
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByText('No target (model decides)')).toBeNull();
  });
});
