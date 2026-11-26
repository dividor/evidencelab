import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown, { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { parseDocLink, repositoryFileUrl } from '../../utils/docLinks';
import { docsArticleUrl } from '../../utils/docsLocation';

const LONG_ARTICLE_WORDS = 1500;

interface DocsArticleProps {
  basePath: string;
  path: string;
  text: string;
  anchor: string;
  onNavigate: (path: string, anchor: string) => void;
}

const HEADING_SELECTOR = 'h2, h3, h4, h5, h6';

const slugify = (text: string) =>
  text.toLowerCase().trim().replace(/[^\p{L}\p{M}\p{N}_\s-]/gu, '').replace(/\s/g, '-');

const legacySlug = (text: string) =>
  text.toLowerCase().trim().replace(/[^a-z0-9\s-]/g, '').replace(/[\s-]+/g, '-');

const assignHeadingIds = (article: HTMLElement) => {
  const ids = new Set<string>();
  const headings = Array.from(article.querySelectorAll<HTMLHeadingElement>(HEADING_SELECTOR));
  for (const heading of headings) {
    const slug = slugify(heading.textContent || '') || 'section';
    let id = slug;
    for (let suffix = 1; ids.has(id); suffix += 1) {
      id = `${slug}-${suffix}`;
    }
    heading.id = id;
    ids.add(id);
  }
  return headings;
};

const markdownComponents = (
  path: string,
  basePath: string,
  onNavigate: DocsArticleProps['onNavigate']
): Components => ({
  img: ({ node, src, alt, ...props }) => {
    const link = parseDocLink(src, path);
    const resolved = link.kind === 'image' ? `${basePath}/docs/${link.path}` : src;
    return <img src={resolved} alt={alt || ''} {...props} />;
  },
  a: ({ node, href, children, ...props }) => {
    const link = parseDocLink(href, path);
    if (link.kind === 'page') {
      return (
        <a
          href={docsArticleUrl(basePath, link.path, link.anchor)}
          onClick={(event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            onNavigate(link.path, link.anchor);
          }}
          {...props}
        >
          {children}
        </a>
      );
    }
    if (link.kind === 'repo-file') {
      return <a href={repositoryFileUrl(link.path)} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
    }
    if (link.kind === 'external') {
      return <a href={link.href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
    }
    return <a href={href} {...props}>{children}</a>;
  },
});

const DocsToc = ({ headings, activeHeading }: {
  headings: HTMLHeadingElement[];
  activeHeading: string;
}) => (
  <nav aria-label="On this page">
    {headings.map((heading) => (
      <a
        key={heading.id}
        href={`#${heading.id}`}
        className={`docs-toc-item${heading.tagName === 'H3' ? ' docs-toc-indent' : ''}`}
        aria-current={heading.id === activeHeading ? 'location' : undefined}
      >
        {heading.textContent}
      </a>
    ))}
  </nav>
);

const DocsArticle = ({ basePath, path, text, anchor, onNavigate }: DocsArticleProps) => {
  const articleRef = useRef<HTMLElement>(null);
  const [headings, setHeadings] = useState<HTMLHeadingElement[]>([]);
  const [activeHeading, setActiveHeading] = useState('');
  const markdown = useMemo(() => (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents(path, basePath, onNavigate)}>
      {text}
    </ReactMarkdown>
  ), [path, basePath, onNavigate, text]);

  useLayoutEffect(() => {
    const article = articleRef.current;
    if (!article) return;
    const renderedHeadings = assignHeadingIds(article);
    const wordCount = text.match(/\S+/g)?.length ?? 0;
    setHeadings(wordCount >= LONG_ARTICLE_WORDS
      ? renderedHeadings.filter((heading) => heading.matches('h2, h3'))
      : []);
  }, [markdown, text]);

  useEffect(() => {
    if (!anchor) return;
    const article = articleRef.current;
    if (!article) return;
    const sections = Array.from(article.querySelectorAll<HTMLHeadingElement>(HEADING_SELECTOR));
    // Bookmarks from older versions may use a slug with repeated hyphens collapsed.
    const target = sections.find((section) => section.id === anchor)
      ?? sections.find((section) => legacySlug(section.textContent || '') === anchor);
    if (!target) return;
    const frame = window.requestAnimationFrame(() => target.scrollIntoView());
    return () => window.cancelAnimationFrame(frame);
  }, [anchor, markdown]);

  const hasToc = headings.length >= 2;

  useEffect(() => {
    if (!hasToc) return;
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.find((entry) => entry.isIntersecting);
      if (visible) setActiveHeading(visible.target.id);
    }, { rootMargin: '-10% 0px -65% 0px' });
    headings.forEach((heading) => observer.observe(heading));
    return () => observer.disconnect();
  }, [hasToc, headings]);

  return (
    <>
      <div className="docs-content">
        {hasToc && (
          <details className="docs-toc-inline">
            <summary>On this page</summary>
            <DocsToc headings={headings} activeHeading={activeHeading} />
          </details>
        )}
        <article className="about-content docs-article" ref={articleRef}>
          {markdown}
        </article>
      </div>
      {hasToc && (
        <aside className="docs-toc">
          <div className="docs-toc-title" aria-hidden="true">On this page</div>
          <DocsToc headings={headings} activeHeading={activeHeading} />
        </aside>
      )}
    </>
  );
};

export default DocsArticle;
