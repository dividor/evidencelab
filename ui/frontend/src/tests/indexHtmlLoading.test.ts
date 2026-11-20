import fs from 'fs';
import path from 'path';

// The page the browser shows before the app's JavaScript has loaded.
const html = fs.readFileSync(path.join(__dirname, '../../public/index.html'), 'utf8');

describe('public/index.html loading state', () => {
  test('shows the orbiting-dots spinner inside #root until React replaces it', () => {
    const root = html.slice(html.indexOf('<div id="root">'), html.indexOf('<!-- Static links'));
    expect(root).toContain('class="boot-spinner"');
    expect(root.match(/<span><\/span>/g)).toHaveLength(5);
  });

  test('stays script-free, so the CSP (script-src without unsafe-inline) is unchanged', () => {
    expect(html).not.toMatch(/<script\b/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });

  test('keeps the static links crawlers read', () => {
    expect(html).toContain('<a href="/privacy">');
    expect(html).toContain('<a href="/terms">');
  });
});
