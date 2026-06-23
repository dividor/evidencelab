import React, { useEffect, useState } from 'react';
import ReactMarkdown, { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { APP_BASE_PATH } from '../../config';

// Footer markdown links: open external (http/https) links in a new tab;
// internal links (e.g. /privacy) stay in the same tab.
const footerComponents: Components = {
  a: ({ href, children }) => {
    const external = !!href && /^https?:\/\//i.test(href);
    return external ? (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ) : (
      <a href={href}>{children}</a>
    );
  },
};

interface AppFooterProps {
  // The default footer content, rendered when no footer.md override is present.
  children: React.ReactNode;
}

// Optional footer override. A deployment can ship `footer.md` in its
// CUSTOMIZE_ASSETS folder; the build copies it to public/footer.md. When present
// it fully replaces the default footer with the rendered markdown. A missing
// file falls through to the SPA's index.html, which we detect and ignore.
const AppFooter: React.FC<AppFooterProps> = ({ children }) => {
  const [custom, setCustom] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`${APP_BASE_PATH}/footer.md?t=${Date.now()}`)
      .then((r) => {
        const type = r.headers.get('content-type') || '';
        if (!r.ok || type.includes('html')) return '';
        return r.text();
      })
      .then((text) => {
        const trimmed = text.trim();
        if (active && trimmed && !trimmed.toLowerCase().startsWith('<!doctype')) {
          setCustom(text);
        }
      })
      .catch(() => {
        /* no override — keep the default footer */
      });
    return () => {
      active = false;
    };
  }, []);

  if (custom) {
    return (
      <footer className="app-footer app-footer-custom">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={footerComponents}>
          {custom}
        </ReactMarkdown>
      </footer>
    );
  }
  return <footer className="app-footer">{children}</footer>;
};

export default AppFooter;
