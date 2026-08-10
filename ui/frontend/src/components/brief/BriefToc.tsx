import React, { useEffect, useState } from 'react';
import {
  closestCenter,
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { IconGrip, IconPlus } from './BriefIcons';
import { BriefSection } from './briefTypes';
import { UseBriefReturn } from './useBrief';

const scrollToSection = (id: string): void => {
  const el = document.getElementById(`brief-section-${id}`);
  if (!el) return;
  // Offset for the app's sticky top bar so the heading isn't hidden under it.
  const bar = document.querySelector('.top-bar');
  const offset = (bar instanceof HTMLElement ? bar.offsetHeight : 0) + 16;
  el.style.scrollMarginTop = `${offset}px`;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

// Scroll-spy: the id of the section heading nearest above the viewport top
// (accounting for the sticky top bar), so the TOC can highlight where you are.
const useActiveSection = (sections: BriefSection[]): string | null => {
  const [activeId, setActiveId] = useState<string | null>(null);
  useEffect(() => {
    const track = () => {
      const bar = document.querySelector('.top-bar');
      const offset = (bar instanceof HTMLElement ? bar.offsetHeight : 0) + 80;
      let active: string | null = null;
      for (const section of sections) {
        const el = document.getElementById(`brief-section-${section.id}`);
        if (el && el.getBoundingClientRect().top <= offset) active = section.id;
      }
      setActiveId(active ?? (sections.length ? sections[0].id : null));
    };
    track();
    window.addEventListener('scroll', track, { passive: true });
    window.addEventListener('resize', track);
    return () => {
      window.removeEventListener('scroll', track);
      window.removeEventListener('resize', track);
    };
  }, [sections]);
  return activeId;
};

interface TocRowProps {
  section: BriefSection;
  num: string;
  brief: UseBriefReturn;
  canEdit: boolean;
  active: boolean;
}

const TocRow: React.FC<TocRowProps> = ({ section, num, brief, canEdit, active }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: section.id,
    disabled: !canEdit,
  });
  const [addingSub, setAddingSub] = useState(false);
  const [subName, setSubName] = useState('');
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const closeSub = (): void => {
    setSubName('');
    setAddingSub(false);
  };
  const commitSub = (): void => {
    const name = subName.trim();
    if (name) brief.addSubHeading(section.id, name);
    closeSub();
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`brief-toc-row${section.level === 2 ? ' brief-toc-row-sub' : ''}${
        active ? ' brief-toc-row-active' : ''
      }`}
    >
      <div className="brief-toc-row-line">
        {canEdit && (
          <button
            type="button"
            className="brief-toc-grip"
            aria-label="Drag to reorder heading"
            {...attributes}
            {...listeners}
          >
            <IconGrip size={15} />
          </button>
        )}
        <button type="button" className="brief-toc-jump" onClick={() => scrollToSection(section.id)}>
          {num && <span className="brief-toc-num">{num}</span>}
          <span className="brief-toc-text">{section.title || 'Untitled heading'}</span>
          <span className={`brief-toc-dot brief-toc-dot-${section.status}`} />
        </button>
        {canEdit && (
          <span className="brief-toc-actions">
            {section.level === 1 && (
              <button
                type="button"
                className="brief-toc-act"
                title="Add a sub-heading"
                aria-label="Add a sub-heading"
                onClick={() => setAddingSub(true)}
              >
                <IconPlus size={13} />
              </button>
            )}
            <button
              type="button"
              className="brief-toc-del"
              title="Delete heading"
              aria-label="Delete heading"
              onClick={() => brief.removeSection(section.id)}
            >
              ×
            </button>
          </span>
        )}
      </div>
      {addingSub && (
        <div className="brief-toc-subadd">
          <input
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            className="brief-toc-sub-input"
            value={subName}
            placeholder="Sub-heading name, then Enter…"
            aria-label="New sub-heading name"
            onChange={(e) => setSubName(e.target.value)}
            onBlur={closeSub}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitSub();
              else if (e.key === 'Escape') closeSub();
            }}
          />
        </div>
      )}
    </div>
  );
};

interface BriefTocProps {
  brief: UseBriefReturn;
  canEdit: boolean;
}

/**
 * Table of contents at the top of the brief. Each row jumps to its section; the
 * grip reorders headings (touch- and mouse-friendly via dnd-kit, constrained to
 * sibling moves), and the per-row controls add a (named) sub-heading or delete.
 * The Contents row also carries the heading-numbering toggle.
 */
export const BriefToc: React.FC<BriefTocProps> = ({ brief, canEdit }) => {
  const { sections, numbers, numberHeadings } = brief;
  const activeId = useActiveSection(sections);
  const [addingHeading, setAddingHeading] = useState(false);
  const [headingName, setHeadingName] = useState('');
  const closeHeading = (): void => {
    setHeadingName('');
    setAddingHeading(false);
  };
  const commitHeading = (): void => {
    const name = headingName.trim();
    if (name) brief.addHeading(name);
    closeHeading();
  };
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    // Press-and-hold to drag on touch, so a plain tap/scroll is unaffected.
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onDragEnd = (e: DragEndEvent): void => {
    const { active, over } = e;
    if (over && active.id !== over.id) {
      brief.reorderSiblings(String(active.id), String(over.id));
    }
  };
  return (
    <nav className="brief-toc" aria-label="Brief contents">
      <div className="brief-toc-head">
        <span className="brief-toc-head-label">Contents</span>
        <button
          type="button"
          className="brief-num-toggle-inline"
          role="switch"
          aria-checked={numberHeadings}
          aria-label="Number headings"
          onClick={() => brief.setNumberHeadings(!numberHeadings)}
          title="Show numbering before each heading"
        >
          <span className={`brief-switch${numberHeadings ? ' brief-switch-on' : ''}`}>
            <span className="brief-switch-thumb" />
          </span>
          Number headings
        </button>
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={sections.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          <div className="brief-toc-list">
            {sections.map((s, i) => (
              <TocRow
                key={s.id}
                section={s}
                num={numberHeadings ? numbers[i] : ''}
                brief={brief}
                canEdit={canEdit}
                active={s.id === activeId}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
      {canEdit &&
        (addingHeading ? (
          <input
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            className="brief-toc-sub-input brief-toc-heading-input"
            value={headingName}
            placeholder="Heading name, then Enter…"
            aria-label="New heading name"
            onChange={(e) => setHeadingName(e.target.value)}
            onBlur={closeHeading}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitHeading();
              else if (e.key === 'Escape') closeHeading();
            }}
          />
        ) : (
          <button type="button" className="brief-toc-add" onClick={() => setAddingHeading(true)}>
            <IconPlus size={14} /> Add heading
          </button>
        ))}
    </nav>
  );
};
