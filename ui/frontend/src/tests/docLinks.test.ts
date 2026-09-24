import {
  REPOSITORY_URL,
  parseDocLink,
  repositoryFileUrl,
  resolveDocPath,
} from '../utils/docLinks';

const FROM = 'admin/content-moderation.md';

describe('resolveDocPath', () => {
  test('a bare file name stays in the same folder', () => {
    expect(resolveDocPath(FROM, 'pipeline-configuration.md')).toBe('admin/pipeline-configuration.md');
  });

  test('a parent segment moves to a sibling folder', () => {
    expect(resolveDocPath(FROM, '../overview/terms.md')).toBe('overview/terms.md');
  });

  test('a dot segment is ignored', () => {
    expect(resolveDocPath(FROM, './user-administration.md')).toBe('admin/user-administration.md');
  });

  test('climbing above the docs root keeps the leading parent segments', () => {
    expect(resolveDocPath(FROM, '../../scripts/custom/apply_branding.sh')).toBe(
      '../scripts/custom/apply_branding.sh'
    );
  });
});

describe('parseDocLink', () => {
  test('another page, with its heading', () => {
    expect(parseDocLink('../overview/terms.md#content-policy', FROM)).toEqual({
      kind: 'page',
      path: 'overview/terms.md',
      anchor: 'content-policy',
    });
  });

  test('another page in the same folder, without a heading', () => {
    expect(parseDocLink('pipeline-configuration.md', FROM)).toEqual({
      kind: 'page',
      path: 'admin/pipeline-configuration.md',
      anchor: '',
    });
  });

  test('an image relative to the page', () => {
    expect(parseDocLink('../images/admin/users-panel.png', 'admin/user-administration.md')).toEqual({
      kind: 'image',
      path: 'images/admin/users-panel.png',
    });
  });

  test('a file elsewhere in the repository', () => {
    expect(parseDocLink('../../scripts/custom/apply_branding.sh', 'admin/customization.md')).toEqual({
      kind: 'repo-file',
      path: 'scripts/custom/apply_branding.sh',
    });
  });

  test('the older absolute /docs/ form still resolves', () => {
    expect(parseDocLink('/docs/using-evidence-lab/search.md', 'overview/about.md')).toEqual({
      kind: 'page',
      path: 'using-evidence-lab/search.md',
      anchor: '',
    });
    expect(parseDocLink('/docs/images/evidence-lab.png', 'overview/about.md')).toEqual({
      kind: 'image',
      path: 'images/evidence-lab.png',
    });
  });

  test('external, mailto, same-page and app links are left alone', () => {
    expect(parseDocLink('https://example.org/x', FROM)).toEqual({ kind: 'external', href: 'https://example.org/x' });
    expect(parseDocLink('mailto:x@y.z', FROM)).toEqual({ kind: 'other', href: 'mailto:x@y.z' });
    expect(parseDocLink('#reporting', FROM)).toEqual({ kind: 'anchor', id: 'reporting' });
    expect(parseDocLink('/terms', FROM)).toEqual({ kind: 'other', href: '/terms' });
    expect(parseDocLink(undefined, FROM)).toEqual({ kind: 'other', href: '' });
  });
});

test('repository file links point at the default branch, never a release tag', () => {
  expect(repositoryFileUrl('scripts/custom/apply_branding.sh')).toBe(
    `${REPOSITORY_URL}/blob/main/scripts/custom/apply_branding.sh`
  );
});
