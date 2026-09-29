/**
 * Every link in docs/ must work both on GitHub and in the in-app docs viewer.
 * That means relative links as GitHub renders them (see utils/docLinks.ts):
 * no app routes, no paths rooted at /docs/, no URLs pinned to a release tag,
 * and every relative target must exist.
 */
import * as fs from 'fs';
import * as path from 'path';

import { parseDocLink } from '../utils/docLinks';

// The docs live at the repository root; the Docker image and the dev container
// carry a copy at docs_source/ instead (the same two locations copy-docs.js uses).
const FRONTEND_DIR = path.resolve(__dirname, '../..');
const CHECKOUT_DOCS = path.resolve(FRONTEND_DIR, '../../docs');
const DOCKER_DOCS = path.resolve(FRONTEND_DIR, 'docs_source');
const DOCS_ROOT = fs.existsSync(CHECKOUT_DOCS) ? CHECKOUT_DOCS : DOCKER_DOCS;
if (!fs.existsSync(DOCS_ROOT)) {
  throw new Error(`docs not found at ${CHECKOUT_DOCS} or ${DOCKER_DOCS}`);
}
// Links to other repository files can only be checked for existence from a checkout.
const REPO_ROOT = DOCS_ROOT === CHECKOUT_DOCS ? path.resolve(CHECKOUT_DOCS, '..') : null;

const listMarkdown = (dir: string): string[] =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'plans' ? [] : listMarkdown(full);
    return entry.name.endsWith('.md') ? [full] : [];
  });

/** Targets of markdown links and images outside fenced code blocks: `](target)`. */
const linkTargets = (markdown: string): string[] => {
  const targets: string[] = [];
  let inCode = false;
  for (const line of markdown.split('\n')) {
    if (line.trimStart().startsWith('```')) {
      inCode = !inCode;
      continue;
    }
    if (inCode) continue;
    for (const match of line.matchAll(/\]\(([^)\s]+)\)/g)) {
      targets.push(match[1]);
    }
  }
  return targets;
};

const pages = listMarkdown(DOCS_ROOT).map((file) => ({
  file,
  docPath: path.relative(DOCS_ROOT, file).split(path.sep).join('/'),
  targets: linkTargets(fs.readFileSync(file, 'utf8')),
}));

test('the docs tree was found', () => {
  expect(pages.length).toBeGreaterThan(10);
});

describe.each(pages)('$docPath', ({ docPath, targets }) => {
  test('has no app-route, /docs/-rooted or release-pinned links', () => {
    const offenders = targets.filter(
      (t) =>
        t.startsWith('/') || /github\.com\/[^/]+\/[^/]+\/(blob|tree|raw)\/v\d/i.test(t)
    );
    expect(offenders).toEqual([]);
  });

  test('every relative page and image link points at a file in the docs tree', () => {
    const missing = targets.filter((t) => {
      const link = parseDocLink(t, docPath);
      if (link.kind !== 'page' && link.kind !== 'image') return false;
      return !fs.existsSync(path.join(DOCS_ROOT, link.path));
    });
    expect(missing).toEqual([]);
  });

  test('every repository file link stays inside the repository and, from a checkout, exists', () => {
    const bad = targets.filter((t) => {
      const link = parseDocLink(t, docPath);
      if (link.kind !== 'repo-file') return false;
      if (link.path === '' || link.path.startsWith('..')) return true;
      return REPO_ROOT !== null && !fs.existsSync(path.join(REPO_ROOT, link.path));
    });
    expect(bad).toEqual([]);
  });
});
