import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { APP_BASE_PATH } from '../../config';

// Renders the admin customization guide. Single source of truth: the same
// markdown shipped under docs/ (also shown in the Docs viewer), so the guide
// never drifts between the two places.
const DOC_PATH = `${APP_BASE_PATH}/docs/admin/customization.md`;

const CustomizationManager: React.FC = () => {
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetch(`${DOC_PATH}?t=${Date.now()}`)
      .then((r) => r.text())
      .then((text) => {
        if (active) setContent(text);
      })
      .catch((err) => {
        console.error('Failed to load customization guide:', err);
        if (active) {
          setContent(
            '# Customization\n\nThe customization guide could not be loaded.'
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return <div className="docs-loading">Loading customization guide…</div>;
  }

  return (
    <div className="docs-content customization-guide">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
};

export default CustomizationManager;
