/**
 * Links inside the documentation markdown.
 *
 * The files under docs/ are read in two places: on GitHub, which resolves a
 * link relative to the markdown file that contains it, and in the in-app
 * docs viewer, which fetches each file from /docs/<path>. So the docs use
 * plain relative links, exactly as GitHub renders them: another page is
 * `pipeline-configuration.md` or `../overview/terms.md#content-policy`, an
 * image is `../images/search-guide/filters-crop.png`, and a file elsewhere in
 * the repository is `../../scripts/custom/apply_branding.sh`. Never an app
 * route (`/terms`), never a URL pinned to a release tag, never a path rooted
 * at `/docs/`. The viewer resolves those relative links here against the
 * page being shown.
 */

/** Public repository, for links from the docs to source files. */
export const REPOSITORY_URL = 'https://github.com/dividor/evidencelab';

const IMAGE_EXTENSIONS = /\.(png|jpe?g|gif|svg|webp)$/i;

export type DocLink =
  | { kind: 'external'; href: string }
  | { kind: 'anchor'; id: string }
  | { kind: 'page'; path: string; anchor: string }
  | { kind: 'image'; path: string }
  | { kind: 'repo-file'; path: string }
  | { kind: 'other'; href: string };

/**
 * Resolve `target` against the directory of `fromPath`, both relative to the
 * docs root (for example `admin/content-moderation.md`). `..` segments may
 * climb above the docs root, which yields a repository path such as
 * `../scripts/custom/apply_branding.sh`; those are returned with the leading
 * `..` intact so the caller can tell them apart from docs paths.
 */
export const resolveDocPath = (fromPath: string, target: string): string => {
  const base = fromPath.split('/').slice(0, -1);
  const segments = base.concat(target.split('/'));
  const out: string[] = [];
  for (const segment of segments) {
    if (segment === '' || segment === '.') continue;
    if (segment === '..') {
      if (out.length > 0 && out[out.length - 1] !== '..') out.pop();
      else out.push('..');
      continue;
    }
    out.push(segment);
  }
  return out.join('/');
};

const isDocsRelative = (href: string): boolean =>
  !href.startsWith('/') && !/^[a-z][a-z0-9+.-]*:/i.test(href);

/** Classify a markdown link found on the page at `fromPath`. */
export const parseDocLink = (href: string | undefined, fromPath: string): DocLink => {
  if (!href) return { kind: 'other', href: '' };
  if (href.startsWith('#')) return { kind: 'anchor', id: href.slice(1) };
  if (/^https?:\/\//i.test(href)) return { kind: 'external', href };

  // Older pages linked with an absolute /docs/ prefix; keep those working.
  const relative = href.startsWith('/docs/') ? href.slice('/docs/'.length) : href;
  if (!isDocsRelative(relative)) return { kind: 'other', href };

  const [pathPart, ...anchorParts] = relative.split('#');
  const anchor = anchorParts.join('#');
  const resolved = href.startsWith('/docs/') ? pathPart : resolveDocPath(fromPath, pathPart);

  if (resolved.startsWith('../')) {
    return { kind: 'repo-file', path: resolved.replace(/^(\.\.\/)+/, '') };
  }
  if (/\.md$/i.test(resolved)) return { kind: 'page', path: resolved, anchor };
  if (IMAGE_EXTENSIONS.test(resolved)) return { kind: 'image', path: resolved };
  return { kind: 'other', href };
};

/** GitHub URL for a file in the repository, on the default branch. */
export const repositoryFileUrl = (path: string): string => `${REPOSITORY_URL}/blob/main/${path}`;
