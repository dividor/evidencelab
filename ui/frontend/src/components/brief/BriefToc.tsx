import React from 'react';
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
  document
    .getElementById(`brief-section-${id}`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

interface TocRowProps {
  section: BriefSection;
  num: string;
  brief: UseBriefReturn;
  canEdit: boolean;
}

const TocRow: React.FC<TocRowProps> = ({ section, num, brief, canEdit }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: section.id,
    disabled: !canEdit,
  });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`brief-toc-row${section.level === 2 ? ' brief-toc-row-sub' : ''}`}
    >
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
              onClick={() => brief.addSubHeading(section.id)}
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
  );
};

interface BriefTocProps {
  brief: UseBriefReturn;
  canEdit: boolean;
}

/**
 * Table of contents at the top of the brief. Each row jumps to its section; the
 * grip reorders headings (touch- and mouse-friendly via dnd-kit, constrained to
 * sibling moves by reorderSiblings), and the per-row controls add sub-headings
 * or delete. "Add heading" appends a new top-level section.
 */
export const BriefToc: React.FC<BriefTocProps> = ({ brief, canEdit }) => {
  const { sections, numbers, numberHeadings } = brief;
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
      <div className="brief-toc-head">Contents</div>
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
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
      {canEdit && (
        <button type="button" className="brief-toc-add" onClick={brief.addHeading}>
          <IconPlus size={14} /> Add heading
        </button>
      )}
    </nav>
  );
};
