/**
 * Rating stars were shown only to signed-in users. These tests pin when a
 * visitor who is not signed in sees them too.
 */
import { canRateWith } from '../ratingAccess';

describe('canRateWith', () => {
  test('lets a signed-in user rate', () => {
    expect(canRateWith(true, true, false)).toBe(true);
  });

  test('hides ratings from anonymous visitors when anonymous ratings are off', () => {
    expect(canRateWith(false, true, false)).toBe(false);
  });

  test('lets anonymous visitors rate when anonymous ratings are on', () => {
    expect(canRateWith(false, true, true)).toBe(true);
  });

  test('hides ratings when the user module is off, whatever the setting', () => {
    expect(canRateWith(false, false, true)).toBe(false);
    expect(canRateWith(true, false, true)).toBe(false);
  });
});
