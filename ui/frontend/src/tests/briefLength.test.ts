import {
  BRIEF_LENGTH,
  buildCondenseInstruction,
  clampTargetWords,
  countWords,
  describeTarget,
  exceedsTarget,
  maxWordsFor,
} from '../components/brief/briefLength';
import { isLikelyNonAnswer } from '../utils/briefStream';

describe('brief length config', () => {
  test('is read from config.json with presets, bounds and a tolerance', () => {
    expect(BRIEF_LENGTH.presets.map((p) => p.label)).toEqual(['Short', 'Standard', 'Long']);
    expect(BRIEF_LENGTH.min).toBeLessThan(BRIEF_LENGTH.presets[0].words);
    expect(BRIEF_LENGTH.max).toBeGreaterThan(BRIEF_LENGTH.presets[2].words);
    expect(BRIEF_LENGTH.tolerance).toBeGreaterThan(0);
  });
});

describe('countWords', () => {
  test('counts prose words and ignores citation markers and markdown syntax', () => {
    expect(countWords('Enrolment rose by 12% in 2023 [1]. It fell later [2, 3].')).toBe(9);
    expect(countWords('## Heading\n\n- **bold** item\n- _em_ item')).toBe(5);
    expect(countWords('')).toBe(0);
    expect(countWords('[1][2] --- ***')).toBe(0);
  });

  test('counts words in any script', () => {
    expect(countWords('L’évaluation a constaté une hausse')).toBe(5);
    expect(countWords('评估 发现 入学率 上升')).toBe(4);
  });
});

describe('exceedsTarget', () => {
  test('allows the tolerance band above the target', () => {
    expect(maxWordsFor(400, 0.25)).toBe(500);
    expect(exceedsTarget(500, 400, 0.25)).toBe(false);
    expect(exceedsTarget(501, 400, 0.25)).toBe(true);
  });

  test('no target means nothing to enforce', () => {
    expect(exceedsTarget(5000, null)).toBe(false);
    expect(exceedsTarget(5000, undefined)).toBe(false);
  });

  test('uses the configured tolerance by default', () => {
    const limit = Math.round(200 * (1 + BRIEF_LENGTH.tolerance));
    expect(exceedsTarget(limit, 200)).toBe(false);
    expect(exceedsTarget(limit + 1, 200)).toBe(true);
  });
});

describe('clampTargetWords / describeTarget', () => {
  test('clamps to the configured range and rounds', () => {
    expect(clampTargetWords(1)).toBe(BRIEF_LENGTH.min);
    expect(clampTargetWords(999999)).toBe(BRIEF_LENGTH.max);
    expect(clampTargetWords(333.4)).toBe(333);
  });

  test('names presets and custom targets', () => {
    expect(describeTarget(350)).toBe('Standard (~350 words)');
    expect(describeTarget(275)).toBe('~275 words');
    expect(describeTarget(null)).toBe('No target');
  });
});

describe('buildCondenseInstruction', () => {
  test('states the target, the current length and keeps citations', () => {
    const instruction = buildCondenseInstruction(150, 240);
    expect(instruction).toContain('approximately 150 words');
    expect(instruction).toContain('currently about 240 words');
    expect(instruction).toContain('[n] citation marker');
  });
});

describe('isLikelyNonAnswer with a length target', () => {
  const short = 'The programme raised enrolment across the districts it covered. '.repeat(6); // ~390 chars

  test('without a target, short uncited text after reading sources is a non-answer', () => {
    expect(isLikelyNonAnswer(short, 5)).toBe(true);
  });

  test('with a short target, the same text is a complete answer', () => {
    expect(isLikelyNonAnswer(short, 5, 100)).toBe(false);
  });

  test('a target never raises the bar above the default', () => {
    expect(isLikelyNonAnswer(short, 5, 2000)).toBe(true);
  });
});
