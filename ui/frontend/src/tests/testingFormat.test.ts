/**
 * Unit tests for the testing-harness formatting helpers.
 */

import {
  formatCostUsd,
  formatTokens,
} from '../components/admin/testing/testingFormat';

describe('formatTokens', () => {
  test('formats counts with locale separators', () => {
    expect(formatTokens(1234567)).toBe((1234567).toLocaleString());
    expect(formatTokens(0)).toBe('0');
  });

  test('renders dash for missing values', () => {
    expect(formatTokens(null)).toBe('-');
    expect(formatTokens(undefined)).toBe('-');
  });
});

describe('formatCostUsd', () => {
  test('formats cost with 4 decimals and dollar sign', () => {
    expect(formatCostUsd(0.00304)).toBe('$0.0030');
    expect(formatCostUsd(1.5)).toBe('$1.5000');
  });

  test('renders dash for missing values', () => {
    expect(formatCostUsd(null)).toBe('-');
    expect(formatCostUsd(undefined)).toBe('-');
  });
});
