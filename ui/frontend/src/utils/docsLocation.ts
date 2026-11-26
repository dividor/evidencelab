import { useSyncExternalStore } from 'react';

export type DocsSection = 'docs' | 'admin';

const DOCS_LOCATION_CHANGE = 'docs-location-change';
const isDocArticlePath = (path: string) =>
  path.endsWith('.md') && path.split('/').every((part) => /^[a-z0-9_-]+(\.md)?$/i.test(part));

export const docsSectionForPath = (path: string): DocsSection =>
  path.startsWith('admin/') ? 'admin' : 'docs';

const subscribe = (callback: () => void) => {
  window.addEventListener('popstate', callback);
  window.addEventListener('hashchange', callback);
  window.addEventListener(DOCS_LOCATION_CHANGE, callback);
  return () => {
    window.removeEventListener('popstate', callback);
    window.removeEventListener('hashchange', callback);
    window.removeEventListener(DOCS_LOCATION_CHANGE, callback);
  };
};

const getLocation = () => window.location.href;

export const notifyDocsLocation = () =>
  window.dispatchEvent(new Event(DOCS_LOCATION_CHANGE));

export const useDocsLocation = (initialPath = '') => {
  const url = new URL(useSyncExternalStore(subscribe, getLocation));
  const requestedPath = url.searchParams.get('path');
  const path = requestedPath && isDocArticlePath(requestedPath) ? requestedPath : initialPath;
  const section = path
    ? docsSectionForPath(path)
    : url.searchParams.get('section') === 'admin' ? 'admin' : 'docs';
  return { section, path, anchor: url.hash.slice(1) };
};

export const docsArticleUrl = (basePath: string, path: string, anchor = '', search = '') => {
  const params = new URLSearchParams(search);
  params.set('tab', 'docs');
  params.set('path', path);
  params.delete('section');
  const hash = anchor ? '#' + anchor : '';
  return `${basePath}/?${params}${hash}`;
};
