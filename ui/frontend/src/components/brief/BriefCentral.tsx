import React, { useState } from 'react';
import { recordTemplateUse } from './briefCentralApi';
import {
  BriefNewModal,
  BriefShareModal,
  BriefTemplateModal,
  BriefVoiceModal,
  NewBriefSubmit,
  TemplateDraft,
  VoiceDraft,
  numberHeadings,
} from './BriefCentralModals';
import { IconEdit, IconPlus, IconShare } from './BriefIcons';
import { BriefListItem, BriefTemplate, VoiceProfile } from './briefTypes';
import { CentralTab, UseBriefCentralReturn } from './useBriefCentral';

/**
 * Brief Central — the Brief tab's landing page. Four tabs: the user's briefs,
 * briefs shared with them (viewer-only), templates and voice & tone profiles.
 */

const formatWhen = (iso: string): string => {
  try {
    const d = new Date(iso);
    return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} · ${d.toLocaleTimeString(
      undefined,
      { hour: 'numeric', minute: '2-digit' },
    )}`;
  } catch {
    return '';
  }
};

const TAB_LABELS: Record<CentralTab, (c: UseBriefCentralReturn) => string> = {
  mine: (c) => `My briefs (${c.myBriefs.length})`,
  shared: (c) => `Shared with me (${c.sharedBriefs.length})`,
  templates: (c) => `Templates (${c.templates.length})`,
  voices: (c) => `Voice & tone (${c.voices.length})`,
};

const BriefCard: React.FC<{
  brief: BriefListItem;
  voiceName: string | null;
  shared: boolean;
  onOpen: () => void;
  onShare?: () => void;
  onDelete?: () => void;
}> = ({ brief, voiceName, shared, onOpen, onShare, onDelete }) => (
  <div className="bc-card">
    <button className="bc-card-main" onClick={onOpen}>
      <div className="bc-card-title">{brief.title}</div>
      {brief.query && <div className="bc-card-query">{brief.query}</div>}
      <div className="bc-card-meta">
        {brief.section_count} sections · {brief.source_count} sources ·{' '}
        {formatWhen(brief.updated_at)}
      </div>
    </button>
    <div className="bc-card-foot">
      {shared ? (
        <>
          <span className="bc-chip bc-chip-muted">Viewer</span>
          <span className="bc-card-foot-note">Shared by {brief.owner_name}</span>
        </>
      ) : (
        <>
          <span className="bc-chip">{voiceName || 'No voice'}</span>
          <span className="bc-card-foot-note">
            {brief.share_count ? `Shared with ${brief.share_count}` : 'Private'}
          </span>
          <button className="bc-card-act" title="Share this brief" onClick={onShare}>
            <IconShare size={12} /> Share
          </button>
          <button
            className="bc-icon-btn bc-icon-danger"
            title="Delete this brief"
            aria-label="Delete this brief"
            onClick={onDelete}
          >
            ×
          </button>
        </>
      )}
    </div>
  </div>
);

const TemplateCard: React.FC<{
  template: BriefTemplate;
  onUse: () => void;
  onDelete: () => void;
}> = ({ template, onUse, onDelete }) => (
  <div className="bc-card">
    <div className="bc-card-main bc-card-static">
      <div className="bc-card-title">{template.name}</div>
      {template.description && <div className="bc-card-query">{template.description}</div>}
      <div className="bc-template-headings">
        {numberHeadings(template.headings).map((h, i) => (
          <div key={i} className={`bc-heading-row${h.sub ? ' bc-heading-sub' : ''}`}>
            <span className="bc-heading-num">{h.num}</span>
            <span>{h.title}</span>
          </div>
        ))}
      </div>
    </div>
    <div className="bc-card-foot">
      <span className="bc-card-foot-note">
        {template.headings.length} headings
        {template.with_text ? ' · includes text' : ''}
        {template.use_count ? ` · used ${template.use_count} times` : ''}
      </span>
      <button className="bc-card-act bc-card-act-right" title="Use this template" onClick={onUse}>
        <IconPlus size={12} /> Use
      </button>
      <button
        className="bc-icon-btn bc-icon-danger"
        title="Delete template"
        aria-label="Delete template"
        onClick={onDelete}
      >
        ×
      </button>
    </div>
  </div>
);

const VoiceCard: React.FC<{
  voice: VoiceProfile;
  onEdit: () => void;
  onDelete: () => void;
}> = ({ voice, onEdit, onDelete }) => (
  <div className="bc-card">
    <div className="bc-card-main bc-card-static">
      <div className="bc-card-title">{voice.name}</div>
      {voice.description && <div className="bc-card-query">{voice.description}</div>}
      <div className="bc-inline-panel">
        <div className="bc-kicker">Style instructions</div>
        <div className="bc-card-query">
          {voice.instructions.length > 180
            ? `${voice.instructions.slice(0, 180)}…`
            : voice.instructions}
        </div>
      </div>
    </div>
    <div className="bc-card-foot">
      <button className="bc-card-act bc-card-act-right" title="Edit this profile" onClick={onEdit}>
        <IconEdit size={12} /> Edit
      </button>
      <button
        className="bc-icon-btn bc-icon-danger"
        title="Delete profile"
        aria-label="Delete profile"
        onClick={onDelete}
      >
        ×
      </button>
    </div>
  </div>
);

interface BriefCentralProps {
  central: UseBriefCentralReturn;
  onOpenBrief: (id: string) => void;
  onCreateBrief: (args: NewBriefSubmit) => void;
}

export const BriefCentral: React.FC<BriefCentralProps> = ({
  central,
  onOpenBrief,
  onCreateBrief,
}) => {
  const [modal, setModal] = useState<'new' | 'template' | 'voice' | 'share' | null>(null);
  const [newTemplateId, setNewTemplateId] = useState<string | null>(null);
  const [voiceDraft, setVoiceDraft] = useState<VoiceDraft | null>(null);
  const [shareBrief, setShareBrief] = useState<BriefListItem | null>(null);

  const emptyTemplateDraft: TemplateDraft = {
    fromBrief: false,
    name: '',
    description: '',
    headings: [{ title: '', sub: false }],
    withText: false,
  };

  const submitNew = (args: NewBriefSubmit) => {
    setModal(null);
    if (args.template) void recordTemplateUse(args.template.id).catch(() => undefined);
    onCreateBrief(args);
  };

  const gridFor = (tab: CentralTab): React.ReactNode => {
    if (tab === 'mine') {
      return central.myBriefs.map((b) => (
        <BriefCard
          key={b.id}
          brief={b}
          voiceName={central.voiceById(b.voice_profile_id)?.name || null}
          shared={false}
          onOpen={() => onOpenBrief(b.id)}
          onShare={() => {
            setShareBrief(b);
            setModal('share');
          }}
          onDelete={() => void central.removeBrief(b.id).catch(() => undefined)}
        />
      ));
    }
    if (tab === 'shared') {
      return central.sharedBriefs.map((b) => (
        <BriefCard key={b.id} brief={b} voiceName={null} shared onOpen={() => onOpenBrief(b.id)} />
      ));
    }
    if (tab === 'templates') {
      return (
        <>
          <button className="bc-add-card" onClick={() => setModal('template')}>
            <IconPlus size={15} /> New template
          </button>
          {central.templates.map((t) => (
            <TemplateCard
              key={t.id}
              template={t}
              onUse={() => {
                setNewTemplateId(t.id);
                setModal('new');
              }}
              onDelete={() => void central.removeTemplate(t.id).catch(() => undefined)}
            />
          ))}
        </>
      );
    }
    return (
      <>
        <button
          className="bc-add-card"
          onClick={() => {
            setVoiceDraft({ id: null, name: '', description: '', instructions: '' });
            setModal('voice');
          }}
        >
          <IconPlus size={15} /> New voice &amp; tone profile
        </button>
        {central.voices.map((v) => (
          <VoiceCard
            key={v.id}
            voice={v}
            onEdit={() => {
              setVoiceDraft({
                id: v.id,
                name: v.name,
                description: v.description || '',
                instructions: v.instructions,
              });
              setModal('voice');
            }}
            onDelete={() => void central.removeVoice(v.id).catch(() => undefined)}
          />
        ))}
      </>
    );
  };

  return (
    <div className="bc-page">
      <div className="bc-header">
        <div>
          <div className="brief-eyebrow">Brief Central</div>
          <h2 className="bc-title">Turn a topic into a structured, evidence-backed brief</h2>
          <p className="bc-lede">
            A brief generates an outline grounded in the document library, researches each heading
            into cited prose, and exports to Word with citations linked back to the source
            documents.
          </p>
        </div>
        <button
          className="brief-btn brief-btn-primary bc-new-btn"
          onClick={() => {
            setNewTemplateId(null);
            setModal('new');
          }}
        >
          <IconPlus /> New brief
        </button>
      </div>

      {central.error && <div className="brief-error brief-error-banner">{central.error}</div>}

      <div className="bc-tabs" role="tablist">
        {(Object.keys(TAB_LABELS) as CentralTab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={central.tab === t}
            className={`bc-tab${central.tab === t ? ' bc-tab-on' : ''}`}
            onClick={() => central.setTab(t)}
          >
            {TAB_LABELS[t](central)}
          </button>
        ))}
      </div>

      {central.loading ? (
        <div className="bc-empty">Loading…</div>
      ) : (
        <div className="bc-grid">{gridFor(central.tab)}</div>
      )}
      {!central.loading && central.tab === 'mine' && central.myBriefs.length === 0 && (
        <div className="bc-empty">No briefs yet — create your first with “New brief”.</div>
      )}
      {!central.loading && central.tab === 'shared' && central.sharedBriefs.length === 0 && (
        <div className="bc-empty">Nothing has been shared with you yet.</div>
      )}

      {modal === 'new' && (
        <BriefNewModal
          templates={central.templates}
          voices={central.voices}
          initialTemplateId={newTemplateId}
          onSubmit={submitNew}
          onClose={() => setModal(null)}
        />
      )}
      {modal === 'template' && (
        <BriefTemplateModal
          draft={emptyTemplateDraft}
          onSave={async (d) => {
            await central.saveTemplate({
              name: d.name,
              description: d.description || null,
              headings: d.headings,
              withText: d.withText,
            });
            setModal(null);
          }}
          onClose={() => setModal(null)}
        />
      )}
      {modal === 'voice' && voiceDraft && (
        <BriefVoiceModal
          draft={voiceDraft}
          onSave={async (d) => {
            await central.saveVoice({
              id: d.id,
              name: d.name,
              description: d.description || null,
              instructions: d.instructions,
            });
            setModal(null);
          }}
          onDelete={async (id) => {
            await central.removeVoice(id);
            setModal(null);
          }}
          onClose={() => setModal(null)}
        />
      )}
      {modal === 'share' && shareBrief && (
        <BriefShareModal
          briefId={shareBrief.id}
          briefTitle={shareBrief.title}
          onChanged={() => void central.refresh()}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
};
