import React, { useState } from 'react';
import { LibraryKind, recordTemplateUse } from './briefCentralApi';
import {
  BriefNewModal,
  BriefVoiceModal,
  NewBriefSubmit,
  VoiceDraft,
  numberHeadings,
} from './BriefCentralModals';
import { IconCopy, IconEdit, IconPlus, IconShare } from './BriefIcons';
import { BriefShareModal, LibraryShareModal } from './BriefShareDialog';
import {
  BriefTemplateModal,
  TemplateDraft,
  draftFromTemplate,
  draftToPayload,
  emptyTemplateDraft,
} from './BriefTemplateModal';
import { BriefListItem, BriefTemplate, VoiceProfile } from './briefTypes';
import { CentralTab, UseBriefCentralReturn } from './useBriefCentral';

/**
 * Brief Central — the Brief tab's landing page. Four tabs: the user's briefs,
 * briefs shared with them (viewer-only), and the templates and voice & tone
 * profiles the user owns or was given. Shared templates and voices are
 * use-only: they can be used or copied, and only their owner edits them.
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
  mine: (c) => `Saved Briefs (${c.myBriefs.length})`,
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

// Footer of a template or voice card: who it is shared with (owner) or whose
// it is (recipient), then the actions allowed on it.
const LibraryFoot: React.FC<{
  item: { can_edit: boolean; owner_name: string | null; share_count: number };
  note?: string;
  noun: string;
  onUse?: () => void;
  onCopy: () => void;
  onEdit: () => void;
  onShare: () => void;
  onDelete: () => void;
}> = ({ item, note, noun, onUse, onCopy, onEdit, onShare, onDelete }) => (
  <div className="bc-card-foot">
    {item.can_edit ? (
      <span className="bc-card-foot-note">
        {item.share_count ? `Shared with ${item.share_count}` : 'Private'}
        {note ? ` · ${note}` : ''}
      </span>
    ) : (
      <>
        <span className="bc-chip bc-chip-muted">Shared</span>
        <span className="bc-card-foot-note">
          by {item.owner_name}
          {note ? ` · ${note}` : ''}
        </span>
      </>
    )}
    {onUse && (
      <button className="bc-card-act bc-card-act-right" title={`Use this ${noun}`} onClick={onUse}>
        <IconPlus size={12} /> Use
      </button>
    )}
    <button
      className={`bc-card-act${onUse ? '' : ' bc-card-act-right'}`}
      title={`Make your own copy of this ${noun}`}
      onClick={onCopy}
    >
      <IconCopy size={12} /> Copy
    </button>
    {item.can_edit && (
      <>
        <button className="bc-card-act" title={`Edit this ${noun}`} onClick={onEdit}>
          <IconEdit size={12} /> Edit
        </button>
        <button className="bc-card-act" title={`Share this ${noun}`} onClick={onShare}>
          <IconShare size={12} /> Share
        </button>
        <button
          className="bc-icon-btn bc-icon-danger"
          title={`Delete this ${noun}`}
          aria-label={`Delete this ${noun}`}
          onClick={onDelete}
        >
          ×
        </button>
      </>
    )}
  </div>
);

const templateNote = (template: BriefTemplate): string => {
  const prompts = template.headings.filter((h) => h.prompt).length + (template.prompt ? 1 : 0);
  return [
    `${template.headings.length} heading${template.headings.length === 1 ? '' : 's'}`,
    prompts ? `${prompts} prompt${prompts === 1 ? '' : 's'}` : '',
    template.with_text ? 'includes text' : '',
    template.use_count ? `used ${template.use_count} times` : '',
  ]
    .filter(Boolean)
    .join(' · ');
};

interface LibraryActions {
  onUse?: () => void;
  onCopy: () => void;
  onEdit: () => void;
  onShare: () => void;
  onDelete: () => void;
}

const TemplateCard: React.FC<{ template: BriefTemplate } & LibraryActions> = ({
  template,
  ...actions
}) => (
  <div className="bc-card">
    <div className="bc-card-main bc-card-static">
      <div className="bc-card-title">{template.name}</div>
      {template.description && <div className="bc-card-query">{template.description}</div>}
      <div className="bc-template-headings">
        {numberHeadings(template.headings).map((h, i) => (
          <div key={i} className={`bc-heading-row${h.sub ? ' bc-heading-sub' : ''}`}>
            <span className="bc-heading-num">{h.num}</span>
            <span>{h.title}</span>
            {h.hasPrompt && <span className="bc-prompt-mark">prompt</span>}
          </div>
        ))}
      </div>
    </div>
    <LibraryFoot item={template} note={templateNote(template)} noun="template" {...actions} />
  </div>
);

const VoiceCard: React.FC<{ voice: VoiceProfile } & LibraryActions> = ({ voice, ...actions }) => (
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
    <LibraryFoot item={voice} noun="profile" {...actions} />
  </div>
);

interface BriefCentralProps {
  central: UseBriefCentralReturn;
  onOpenBrief: (id: string) => void;
  onCreateBrief: (args: NewBriefSubmit) => void;
  // The team's default section length for a new brief (null = no target).
  defaultTargetWords?: number | null;
}

export const BriefCentral: React.FC<BriefCentralProps> = ({
  central,
  onOpenBrief,
  onCreateBrief,
  defaultTargetWords,
}) => {
  const [modal, setModal] = useState<'new' | 'template' | 'voice' | 'share' | 'library-share' | null>(
    null,
  );
  const [newTemplateId, setNewTemplateId] = useState<string | null>(null);
  const [templateDraft, setTemplateDraft] = useState<TemplateDraft | null>(null);
  const [voiceDraft, setVoiceDraft] = useState<VoiceDraft | null>(null);
  const [shareBrief, setShareBrief] = useState<BriefListItem | null>(null);
  const [libraryShare, setLibraryShare] = useState<{
    kind: LibraryKind;
    id: string;
    name: string;
  } | null>(null);

  const report = (e: unknown, what: string) =>
    central.setError(e instanceof Error ? `${what}: ${e.message}` : what);
  const openTemplate = (draft: TemplateDraft) => {
    setTemplateDraft(draft);
    setModal('template');
  };
  const openLibraryShare = (kind: LibraryKind, id: string, name: string) => {
    setLibraryShare({ kind, id, name });
    setModal('library-share');
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
          <button className="bc-add-card" onClick={() => openTemplate(emptyTemplateDraft())}>
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
              onCopy={() => void central.copyTemplate(t.id).catch((e) => report(e, 'Could not copy'))}
              onEdit={() => openTemplate(draftFromTemplate(t))}
              onShare={() => openLibraryShare('template', t.id, t.name)}
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
            onCopy={() => void central.copyVoice(v.id).catch((e) => report(e, 'Could not copy'))}
            onEdit={() => {
              setVoiceDraft({
                id: v.id,
                name: v.name,
                description: v.description || '',
                instructions: v.instructions,
              });
              setModal('voice');
            }}
            onShare={() => openLibraryShare('voice', v.id, v.name)}
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
            Use AI to help write a brief document based on the document library.
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
          defaultTargetWords={defaultTargetWords}
          onSubmit={submitNew}
          onClose={() => setModal(null)}
        />
      )}
      {modal === 'template' && templateDraft && (
        <BriefTemplateModal
          draft={templateDraft}
          voices={central.voices}
          onSave={async (d) => {
            await central.saveTemplate(d.id, draftToPayload(d));
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
      {modal === 'library-share' && libraryShare && (
        <LibraryShareModal
          kind={libraryShare.kind}
          itemId={libraryShare.id}
          itemName={libraryShare.name}
          onChanged={(count) =>
            libraryShare.kind === 'template'
              ? central.setTemplateShareCount(libraryShare.id, count)
              : central.setVoiceShareCount(libraryShare.id, count)
          }
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
};
