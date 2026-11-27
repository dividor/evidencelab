import React, { useState } from 'react';
import type { CaseEditorProps } from './CaseEditor';

interface Sibling {
  title: string;
  content?: string;
  level?: number;
}

const BriefCaseEditor: React.FC<CaseEditorProps> = ({ initialCase, onSubmit, onCancel, saving, submitLabel }) => {
  const input = initialCase?.input || {};
  const [topic, setTopic] = useState(String(input.query || ''));
  const [heading, setHeading] = useState(String(input.heading || ''));
  const [guidance, setGuidance] = useState(String(input.guidance || ''));
  const [voice, setVoice] = useState(String(input.voice || ''));
  const [words, setWords] = useState(String(input.target_words || ''));
  const [siblings, setSiblings] = useState<Sibling[]>((input.siblings as Sibling[]) || []);
  const [notes, setNotes] = useState(initialCase?.notes || '');
  const [tags, setTags] = useState((initialCase?.tags || []).join(', '));
  const updateSibling = (index: number, change: Partial<Sibling>) =>
    setSiblings(siblings.map((s, i) => i === index ? { ...s, ...change } : s));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    onSubmit({
      input: {
        ...input,
        query: topic.trim(),
        heading: heading.trim(),
        guidance,
        voice,
        target_words: words ? Number(words) : null,
        siblings,
      },
      notes,
      tags: tags.split(',').map(tag => tag.trim()).filter(Boolean),
    });
  };

  return <form className="testing-case-editor brief-experiment-case" onSubmit={submit}>
    <label>
      Brief topic
      <input required value={topic} onChange={e => setTopic(e.target.value)} />
    </label>
    <label>
      Section to generate
      <input required value={heading} onChange={e => setHeading(e.target.value)} />
    </label>
    <label>
      Section instructions
      <textarea value={guidance} onChange={e => setGuidance(e.target.value)} />
    </label>
    <label>
      Voice and audience
      <input value={voice} onChange={e => setVoice(e.target.value)} />
    </label>
    <label>
      Target words
      <input type="number" min="50" max="5000" value={words} onChange={e => setWords(e.target.value)} />
    </label>
    {siblings.map((s, i) => <fieldset key={i}>
      <legend>Other section {i + 1}</legend>
      <label>
        Heading
        <input required value={s.title} onChange={e => updateSibling(i, { title: e.target.value })} />
      </label>
      <label>
        Existing text
        <textarea value={s.content || ''} onChange={e => updateSibling(i, { content: e.target.value })} />
      </label>
      <button type="button" className="btn-sm" onClick={() => setSiblings(siblings.filter((_, j) => j !== i))}>Remove section</button>
    </fieldset>)}
    <button type="button" className="btn-sm" onClick={() => setSiblings([...siblings, { title: '', content: '' }])}>Add another section</button>
    <label>
      Tags
      <input value={tags} onChange={e => setTags(e.target.value)} />
    </label>
    <label>
      Notes
      <textarea value={notes} onChange={e => setNotes(e.target.value)} />
    </label>
    <div className="testing-row-actions">
      <button type="submit" disabled={saving} className="btn-sm btn-primary">{submitLabel}</button>
      <button type="button" className="btn-sm" onClick={onCancel}>Cancel</button>
    </div>
  </form>;
};
export default BriefCaseEditor;
