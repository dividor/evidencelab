import { BRIEF_INTRO_DEFAULTS, BriefIntroConfig, resolveIntroConfig } from '../components/brief/briefIntro';

const KEY = 'application.brief.introductions';

describe('resolveIntroConfig', () => {
  test('uses the configured values', () => {
    expect(resolveIntroConfig({ target_words: 90, heading_retries: 0 })).toEqual({
      target_words: 90,
      heading_retries: 0,
    });
  });

  test('uses the defaults when the setting is missing', () => {
    expect(BRIEF_INTRO_DEFAULTS).toEqual({ target_words: 120, heading_retries: 1 });
    expect(resolveIntroConfig(undefined)).toEqual(BRIEF_INTRO_DEFAULTS);
  });

  test('fills in only the values that are missing', () => {
    expect(resolveIntroConfig({ target_words: 200 })).toEqual({ target_words: 200, heading_retries: 1 });
    expect(resolveIntroConfig({ heading_retries: 3 })).toEqual({ target_words: 120, heading_retries: 3 });
    expect(resolveIntroConfig({})).toEqual(BRIEF_INTRO_DEFAULTS);
  });

  test('a value that is present but invalid is an error naming it', () => {
    expect(() => resolveIntroConfig({ target_words: 0 })).toThrow(`${KEY}.target_words`);
    expect(() => resolveIntroConfig({ target_words: '120' })).toThrow(`${KEY}.target_words`);
    expect(() => resolveIntroConfig({ heading_retries: -1 })).toThrow(`${KEY}.heading_retries`);
    expect(() => resolveIntroConfig({ heading_retries: 1.5 })).toThrow(`${KEY}.heading_retries`);
    expect(() => resolveIntroConfig(null)).toThrow(`${KEY} must be an object`);
    expect(() => resolveIntroConfig(120)).toThrow(`${KEY} must be an object`);
  });
});

describe('BRIEF_INTRO', () => {
  const loadWith = (brief: Record<string, unknown>): BriefIntroConfig => {
    let loaded: BriefIntroConfig | undefined;
    jest.isolateModules(() => {
      jest.doMock('../config.json', () => ({ application: { brief } }));
      loaded = jest.requireActual('../components/brief/briefIntro').BRIEF_INTRO;
    });
    jest.dontMock('../config.json');
    return loaded as BriefIntroConfig;
  };

  test('loads with the defaults from a config.json that predates the setting', () => {
    expect(loadWith({ target_words: { default: null } })).toEqual({ target_words: 120, heading_retries: 1 });
  });

  test('loads the configured values', () => {
    expect(loadWith({ introductions: { target_words: 80, heading_retries: 2 } })).toEqual({
      target_words: 80,
      heading_retries: 2,
    });
  });
});
