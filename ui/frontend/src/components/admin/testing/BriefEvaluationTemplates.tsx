import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL, { APP_BASE_PATH } from '../../../config';
import { docsArticleUrl } from '../../../utils/docsLocation';
import type { TestDataset } from '../../../types/testing';
import { BriefTemplate, VoiceProfile } from '../../brief/briefTypes';
import {
  BriefTemplateModal, draftFromTemplate, draftToPayload, emptyTemplateDraft, TemplateDraft,
} from '../../brief/BriefTemplateModal';
import ConfirmModal from '../ConfirmModal';
import { deleteTemplate, createTemplate, listVoiceProfiles, templateBody } from '../../brief/briefCentralApi';
import '../../brief/brief.css';

export type EvaluationTemplate = Pick<BriefTemplate, 'id' | 'name' | 'description' | 'owner_name'> & {
  can_delete: boolean; section_count: number; sections: string[]; heading_numbers: string[];
};

export const evaluationTemplatesUrl = `${API_BASE_URL}/testing/brief-templates`;

export default function BriefEvaluationTemplates({ dataset, onBack, onViewExperiments }: {
  dataset: TestDataset; onBack: () => void; onViewExperiments: (dataset: TestDataset) => void;
}) {
  const [templates, setTemplates] = useState<EvaluationTemplate[]>([]);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [deleting, setDeleting] = useState<EvaluationTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    const { data } = await axios.get<EvaluationTemplate[]>(evaluationTemplatesUrl);
    setTemplates(data);
  }, []);
  useEffect(() => {
    refresh().catch(() => setError('Could not load Brief templates.')).finally(() => setLoading(false));
  }, [refresh]);
  const open = async (template?: EvaluationTemplate) => {
    setError('');
    try {
      if (template) {
        const url = `${evaluationTemplatesUrl}/${template.id}`;
        const [original, available] = await Promise.all([axios.get<BriefTemplate>(url), axios.get<VoiceProfile[]>(`${url}/voices`)]);
        setVoices(available.data);
        setDraft(draftFromTemplate(original.data));
      } else {
        setVoices(await listVoiceProfiles());
        setDraft(emptyTemplateDraft());
      }
    } catch { setError('Could not open the template editor.'); }
  };
  const save = async (value: TemplateDraft) => {
    const payload = draftToPayload(value);
    if (value.id) await axios.put(`${evaluationTemplatesUrl}/${value.id}`, templateBody(payload));
    else await createTemplate(payload);
    setDraft(null);
    await refresh().catch(() => setError('Saved the template. Reopen the dataset to reload the list.'));
  };
  const remove = async () => {
    if (!deleting) return;
    try { await deleteTemplate(deleting.id); await refresh(); }
    catch { setError('Could not delete the template.'); }
    finally { setDeleting(null); }
  };
  return <section className="admin-section testing-section">
    <div className="testing-editor-header">
      <button type="button" className="btn-sm" onClick={onBack}>← Back to datasets</button>
      <h3>{dataset.name}</h3>
    </div>
    <h4>Brief templates</h4>
    <p>Each record is a Brief Central template. Create a Brief template to add a record here, or edit one to change the sections and instructions your experiment will use.{' '}
      <a href={docsArticleUrl(APP_BASE_PATH, 'using-evidence-lab/brief.md', '7-templates')} target="_blank" rel="noreferrer">How to create and use Brief templates</a>.
    </p>
    <div className="testing-controls">
      <button className="btn-sm btn-primary" onClick={() => void open()}>Create template</button>
      <button className="btn-sm" onClick={() => onViewExperiments(dataset)}>View experiments</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {loading ? <p>Loading templates…</p> : !error && templates.length === 0 ? <p>No Brief templates yet.</p> : (
      <table className="admin-table"><thead><tr><th>Template</th><th>Owner</th><th>Sections</th><th>Actions</th></tr></thead>
        <tbody>{templates.map(t => <tr key={t.id}>
          <td><strong>{t.name}</strong>{t.description && <div>{t.description}</div>}</td>
          <td>{t.owner_name}</td><td>{t.section_count}</td>
          <td><div className="testing-row-actions"><button className="btn-sm" aria-label={`Edit ${t.name}`} onClick={() => void open(t)}>Edit template</button>
            {t.can_delete && <button className="btn-sm btn-danger" aria-label={`Delete ${t.name}`} onClick={() => setDeleting(t)}>Delete</button>}
          </div></td>
        </tr>)}</tbody>
      </table>
    )}
    {deleting && <ConfirmModal title="Delete template" message={`Delete “${deleting.name}” from Brief Central? Experiments using this template will need a new selection. Previous run results are kept.`} confirmLabel="Delete template" onConfirm={remove} onCancel={() => setDeleting(null)} />}
    {draft && <BriefTemplateModal draft={draft} voices={voices} onSave={save} onClose={() => setDraft(null)} backLabel="Back to brief evaluation" />}
  </section>;
}
