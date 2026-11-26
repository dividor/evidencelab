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
  expect(getButton('Share')).toBeVisible();
  expect(getButton('Save as Template')).toBeVisible();
  expect(getButton('Export to Word')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Regenerate All' })).not.toBeInTheDocument();

  fireEvent.click(getButton(wholeBriefAskAi));
  fireEvent.click(getButton('Regenerate All'));
  expect(onRegenerateAll).toHaveBeenCalledTimes(1);
  expect(getButton(wholeBriefAskAi)).toHaveAttribute('aria-expanded', 'false');

  fireEvent.click(getButton(wholeBriefAskAi));
  fireEvent.click(getButton('Get Updates for All Sections'));
  expect(brief.updateAll).toHaveBeenCalledTimes(1);
});

test('a completed section opens the matching AI action and keeps manual editing and history visible', () => {
  const brief = makeBrief();
  render(<BriefDocument brief={brief} showToc={false} />);
  expect(getButton('Manually Edit')).toBeVisible();
  expect(getButton('Section History')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Regenerate' })).not.toBeInTheDocument();

  fireEvent.click(getButton(sectionAskAi));
  fireEvent.click(getButton('Regenerate'));
  expect(brief.openRegen).toHaveBeenCalledWith(section.id);

  fireEvent.click(getButton(sectionAskAi));
  fireEvent.click(getButton('Edit'));
  expect(screen.getByText('Edit “Findings”')).toBeVisible();
  expect(getButton('Apply edit')).toBeDisabled();
  fireEvent.click(getButton('Cancel'));

  fireEvent.click(getButton(sectionAskAi));
  fireEvent.click(getButton('Get Updates'));
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
  const option = getButton('Regenerate');
  act(() => option.focus());
  expect(trigger).toHaveAttribute('aria-expanded', 'true');
  fireEvent.keyDown(option, { key: 'Escape' });
  expect(trigger).toHaveFocus();
  expect(trigger).toHaveAttribute('aria-expanded', 'false');

  fireEvent.click(trigger);
  fireEvent.pointerDown(document.body);
  expect(trigger).toHaveAttribute('aria-expanded', 'false');

  fireEvent.click(trigger);
  act(() => getButton('Manually Edit').focus());
  expect(trigger).toHaveAttribute('aria-expanded', 'false');
  expect(getButton('Manually Edit')).toHaveFocus();
});

test('bulk updates are only offered when a section has finished researching', () => {
  const brief = makeBrief({ sections: [{ ...section, status: 'pending', sample: true }] });
  render(<BriefDocument brief={brief} showToc={false} />);
  fireEvent.click(getButton(wholeBriefAskAi));
  expect(getButton('Regenerate All')).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Get Updates for All Sections' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: sectionAskAi })).not.toBeInTheDocument();
});

test('a running section disables the bulk menu and dismisses its open options', () => {
  const { rerender } = render(<BriefDocument brief={makeBrief()} showToc={false} />);
  fireEvent.click(getButton(wholeBriefAskAi));
  expect(getButton('Regenerate All')).toBeEnabled();
  const running = makeBrief({ sections: [{ ...section, status: 'researching' }] });
  rerender(<BriefDocument brief={running} showToc={false} />);
  expect(getButton(wholeBriefAskAi)).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Regenerate All' })).not.toBeInTheDocument();
});

test('view-only briefs do not offer Ask AI', () => {
  render(<BriefDocument brief={makeBrief({ canEdit: false })} showToc={false} />);
  expect(screen.queryByRole('button', { name: /Ask AI/ })).not.toBeInTheDocument();
  expect(getButton('Section History')).toBeVisible();
});
