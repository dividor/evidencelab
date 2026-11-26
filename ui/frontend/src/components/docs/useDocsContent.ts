import { useCallback, useEffect, useRef, useState } from 'react';
import { applyDeploymentFacts } from '../../utils/deploymentText';

export interface DocNode {
  title: string;
  path: string;
}

export interface DocFolder {
  title: string;
  children: DocNode[];
}

interface DocsManifest {
  title: string;
  tree: DocFolder[];
}

const fetchDocsFile = async (basePath: string, path: string) => {
  const response = await fetch(`${basePath}/docs/${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Documentation request failed (${response.status})`);
  return response;
};

export const useDocsManifest = (basePath: string) => {
  const [manifest, setManifest] = useState<DocsManifest | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    fetchDocsFile(basePath, 'docs.json')
      .then((response) => response.json())
      .then((data: DocsManifest) => { if (current) setManifest(data); })
      .catch((error) => {
        console.error('Failed to load docs manifest:', error);
        if (current) setFailed(true);
      });
    return () => { current = false; };
  }, [basePath]);

  return { manifest, failed };
};

export const useDocsReader = (basePath: string) => {
  const requests = useRef(new Map<string, Promise<string>>());

  return useCallback((path: string) => {
    const key = `${basePath}/${path}`;
    const cached = requests.current.get(key);
    if (cached) return cached;

    const request = fetchDocsFile(basePath, path)
      .then((response) => response.text())
      .then(applyDeploymentFacts)
      .catch((error) => {
        requests.current.delete(key);
        throw error;
      });
    requests.current.set(key, request);
    return request;
  }, [basePath]);
};

type ReadDoc = ReturnType<typeof useDocsReader>;
type Article = { path: string; text: string; failed?: false } | { path: string; failed: true };

export const useDocsArticle = (path: string, readDoc: ReadDoc) => {
  const [article, setArticle] = useState<Article | null>(null);

  useEffect(() => {
    if (!path) return;
    let current = true;
    readDoc(path)
      .then((text) => { if (current) setArticle({ path, text }); })
      .catch((error) => {
        console.error('Failed to load doc:', error);
        if (current) setArticle({ path, failed: true });
      });
    return () => { current = false; };
  }, [path, readDoc]);

  return article?.path === path ? article : null;
};

interface SearchIndex {
  docs: DocNode[];
  content: Map<string, string> | null;
}

export const useDocsSearch = (docs: DocNode[], searchQuery: string, readDoc: ReadDoc) => {
  const [index, setIndex] = useState<SearchIndex | null>(null);
  const query = searchQuery.trim().toLowerCase();
  const isSearching = Boolean(query);

  useEffect(() => {
    if (!isSearching) return;
    let current = true;
    Promise.all(docs.map(async ({ path }) => [path, await readDoc(path)] as const))
      .then((entries) => { if (current) setIndex({ docs, content: new Map(entries) }); })
      .catch((error) => {
        console.error('Failed to search docs:', error);
        if (current) setIndex({ docs, content: null });
      });
    return () => { current = false; };
  }, [docs, isSearching, readDoc]);

  if (!isSearching) return { results: null };
  const currentIndex = index?.docs === docs ? index : null;
  const titles = new Set(docs.filter((doc) => doc.title.toLowerCase().includes(query)));
  const contentMatches = docs.filter(
    (doc) => !titles.has(doc) && currentIndex?.content?.get(doc.path)?.toLowerCase().includes(query)
  );
  return {
    results: [...titles, ...contentMatches],
    status: currentIndex ? (currentIndex.content ? '' : 'Could not search article text.') : 'Searching…',
  };
};
