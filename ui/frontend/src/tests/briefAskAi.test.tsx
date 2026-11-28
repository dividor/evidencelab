import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { BriefDocument } from '../components/brief/BriefDocument';
import type { BriefSection } from '../components/brief/briefTypes';
import type { UseBriefReturn } from '../components/brief/useBrief';

const section: BriefSection = {
  id: 'findings',
  title: 'Findings',
  level: 1,
  status: 'done',
  progress: 100,
  content: 'School attendance improved.',
  sources: [],
  activity: [],
};

const makeBrief = (overrides: Partial<UseBriefReturn> = {}) =>
  ({
    briefTitle: 'School meals',
    sections: [section],
    generatingActivity: [],
    references: [],
    referenceGroups: [],
    totalWords: 3,
    totalSources: 0,
    canEdit: true,
    remote: true,
    stage: 'done',
    researching: (overrides.sections ?? [section]).some((s) => s.status === 'researching'),
    openRegen: jest.fn(),
    reviseSection: jest.fn(),
    updateAll: jest.fn(),
    ...overrides,
  }) as UseBriefReturn;

const AI_REGENERATE = 'AI Regenerate';
const MORE_ACTIONS = 'More actions';
const REGENERATE_ALL = 'AI Regenerate All Sections';
const EXPANDED = 'aria-expanded';
const wholeBriefAskAi = 'Ask AI for the whole brief';
const sectionAskAi = 'Ask AI for Findings';
const getButton = (name: string) => screen.getByRole('button', { name, exact: true });

test('the Brief header groups the existing whole-brief actions under Ask AI', () => {
  const brief = makeBrief();
  const onRegenerateAll = jest.fn();
  render(
    <BriefDocument
      brief={brief}
      showToc={false}
      onRegenerateAll={onRegenerateAll}
      onOpenShare={jest.fn()}
      onSaveTemplate={jest.fn()}
      onExportWord={jest.fn()}
    />,
  );
  expect(screen.queryByRole('button', { name: 'Share', exact: true })).toBeNull();
  fireEvent.click(getButton(MORE_ACTIONS));
  expect(getButton('Share')).toBeVisible();
  expect(getButton('Save as Template')).toBeVisible();
  expect(getButton('Export to Word')).toBeVisible();
  expect(screen.queryByRole('button', { name: REGENERATE_ALL })).not.toBeInTheDocument();

  fireEvent.click(getButton(wholeBriefAskAi));
  fireEvent.click(getButton(REGENERATE_ALL));
  expect(onRegenerateAll).toHaveBeenCalledTimes(1);
  expect(getButton(wholeBriefAskAi)).toHaveAttribute(EXPANDED, 'false');

  fireEvent.click(getButton(wholeBriefAskAi));
  fireEvent.click(getButton('AI Get Updates for All Sections'));
  expect(brief.updateAll).toHaveBeenCalledTimes(1);
});

test('the same viewport compacts toolbar actions when its available width shrinks', () => {
  const reports = new Map<Element, (width: number) => void>();
  const measure = jest.spyOn(window, 'ResizeObserver').mockImplementation(callback => {
    const observer = {
      observe: (target: Element) => {
        reports.set(target, width => {
          const size = { inlineSize: width, blockSize: 44 };
          const contentRect = {
            x: 0, y: 0, width, height: 44, top: 0, bottom: 44, left: 0, right: width, toJSON: () => ({}),
          };
          callback([{ target, contentRect, borderBoxSize: [size],
            contentBoxSize: [size], devicePixelContentBoxSize: [size] }], observer);
        });
      },
      unobserve: jest.fn(),
      disconnect: jest.fn(),
    };
    return observer;
  });
  try {
    const brief = makeBrief();
    const regenerate = jest.fn();
    const { unmount } = render(<BriefDocument brief={brief} showToc={false} onRegenerateAll={regenerate} />);
    const toolbar = screen.getByRole('group', { name: 'Whole document actions' });
    const reportWidth = reports.get(toolbar);
    expect(reportWidth).toBeDefined();

    act(() => { reportWidth?.(1440); });
    fireEvent.click(getButton(REGENERATE_ALL));
    expect(regenerate).toHaveBeenCalledTimes(1);
    fireEvent.click(getButton('AI Get Updates for All Sections'));
    expect(brief.updateAll).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: wholeBriefAskAi })).toBeNull();

    act(() => { reportWidth?.(960); });
    expect(screen.queryByRole('button', { name: REGENERATE_ALL })).toBeNull();
    fireEvent.click(getButton(wholeBriefAskAi));
    expect(getButton(REGENERATE_ALL)).toBeVisible();

    unmount();
    expect(measure.mock.results.some(({ value }) => value.disconnect.mock.calls.length > 0)).toBe(true);
  } finally {
    measure.mockRestore();
  }
});

test('a completed section opens the matching AI action and keeps Edit visible and puts history in More', () => {
  const brief = makeBrief();
  render(<BriefDocument brief={brief} showToc={false} />);
  expect(getButton('Edit')).toBeVisible();
  fireEvent.click(getButton('More actions for Findings'));
  expect(getButton('Section History')).toBeVisible();
  fireEvent.click(getButton('More actions for Findings'));
  expect(screen.queryByRole('button', { name: AI_REGENERATE })).not.toBeInTheDocument();

  fireEvent.click(getButton(sectionAskAi));
  fireEvent.click(getButton(AI_REGENERATE));
  expect(brief.openRegen).toHaveBeenCalledWith(section.id);

  fireEvent.click(getButton(sectionAskAi));
  fireEvent.click(getButton('AI Edit'));
  expect(screen.getByText('Edit “Findings”')).toBeVisible();
  expect(getButton('Apply edit')).toBeDisabled();
  fireEvent.click(getButton('Cancel'));

  fireEvent.click(getButton(sectionAskAi));
  fireEvent.click(getButton('AI Get Updates'));
  expect(screen.getByText('Update “Findings”')).toBeVisible();
  expect(getButton('Run update')).toBeEnabled();
  expect(brief.reviseSection).not.toHaveBeenCalled();
  fireEvent.click(getButton('Run update'));
  expect(brief.reviseSection).toHaveBeenCalledWith(section.id, 'update', null);
});

test('Escape returns focus to Ask AI, and outside clicks or focus dismiss the options', () => {
  render(<BriefDocument brief={makeBrief()} showToc={false} />);
  const trigger = getButton(sectionAskAi);
  fireEvent.click(trigger);
  const option = getButton(AI_REGENERATE);
  act(() => option.focus());
  expect(trigger).toHaveAttribute(EXPANDED, 'true');
  fireEvent.keyDown(option, { key: 'Escape' });
  expect(trigger).toHaveFocus();
  expect(trigger).toHaveAttribute(EXPANDED, 'false');

  fireEvent.click(trigger);
  fireEvent.pointerDown(document.body);
  expect(trigger).toHaveAttribute(EXPANDED, 'false');

  fireEvent.click(trigger);
  const manualEdit = screen.getAllByRole('button', { name: 'Edit', exact: true }).find(button => button.classList.contains('brief-regen-btn'))!;
  act(() => manualEdit.focus());
  expect(trigger).toHaveAttribute(EXPANDED, 'false');
  expect(manualEdit).toHaveFocus();
});

test('bulk updates are only offered when a section has finished researching', () => {
  const brief = makeBrief({ sections: [{ ...section, status: 'pending', sample: true }] });
  render(<BriefDocument brief={brief} showToc={false} />);
  fireEvent.click(getButton(wholeBriefAskAi));
  expect(getButton(REGENERATE_ALL)).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'AI Get Updates for All Sections' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: sectionAskAi })).not.toBeInTheDocument();
});

test('a running section disables the bulk menu and dismisses its open options', () => {
  const { rerender } = render(<BriefDocument brief={makeBrief()} showToc={false} />);
  fireEvent.click(getButton(wholeBriefAskAi));
  expect(getButton(REGENERATE_ALL)).toBeEnabled();
  const running = makeBrief({ sections: [{ ...section, status: 'researching' }] });
  rerender(<BriefDocument brief={running} showToc={false} />);
  expect(getButton(wholeBriefAskAi)).toBeDisabled();
  expect(screen.queryByRole('button', { name: REGENERATE_ALL })).not.toBeInTheDocument();
});

test('view-only briefs do not offer Ask AI', () => {
  render(<BriefDocument brief={makeBrief({ canEdit: false })} showToc={false} />);
  expect(screen.queryByRole('button', { name: /Ask AI/ })).not.toBeInTheDocument();
  expect(getButton('Section History')).toBeVisible();
});

test('More actions opens Share and Export and disables export while busy', () => {
  const onShare = jest.fn();
  const onExport = jest.fn();
  const { rerender } = render(<BriefDocument brief={makeBrief()} showToc={false} onOpenShare={onShare} onExportWord={onExport} />);
  fireEvent.click(getButton(MORE_ACTIONS));
  fireEvent.click(getButton('Share'));
  expect(onShare).toHaveBeenCalledTimes(1);
  expect(getButton(MORE_ACTIONS)).toHaveAttribute(EXPANDED, 'false');
  fireEvent.click(getButton(MORE_ACTIONS));
  fireEvent.click(getButton('Export to Word'));
  expect(onExport).toHaveBeenCalledTimes(1);
  rerender(<BriefDocument brief={makeBrief()} showToc={false} onExportWord={onExport} exportBusy />);
  fireEvent.click(getButton(MORE_ACTIONS));
  expect(getButton('Exporting…')).toBeDisabled();
});
