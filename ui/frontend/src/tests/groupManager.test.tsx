import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

// Mock config
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
}));

// Mock axios — note: `delete` is a JS keyword so jest.mock doesn't auto-mock it.
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;
if (!mockedAxios.delete) {
  (mockedAxios as any).delete = jest.fn();
}

import GroupManager from '../components/admin/GroupManager';

const mockGroups = [
  {
    id: 'group-1',
    name: 'Default',
    description: 'The default group',
    is_default: true,
    created_at: '2024-01-01',
    datasource_keys: ['UNEG'],
    member_count: 3,
  },
  {
    id: 'group-2',
    name: 'Analysts',
    description: 'Analyst team',
    is_default: false,
    created_at: '2024-01-02',
    datasource_keys: ['UNEG', 'ACLED'],
    member_count: 2,
  },
];

const mockUsers = [
  {
    id: 'user-1',
    email: 'alice@test.com',
    first_name: 'Alice',
    last_name: null,
    display_name: 'Alice',
    is_active: true,
    is_verified: true,
    is_superuser: false,
  },
  {
    id: 'user-2',
    email: 'bob@test.com',
    first_name: 'Bob',
    last_name: null,
    display_name: 'Bob',
    is_active: true,
    is_verified: true,
    is_superuser: false,
  },
];

const mockMembers = [
  { id: 'user-1', email: 'alice@test.com', first_name: 'Alice', last_name: null, display_name: 'Alice', is_active: true },
];

const mockDatasources = ['UNEG', 'ACLED', 'OCHA'];

describe('GroupManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    mockedAxios.get.mockImplementation((url: string) => {
      if (url.includes('/groups/datasource-keys')) {
        return Promise.resolve({ data: mockDatasources });
      }
      if (url.includes('/groups/') && url.includes('/members')) {
        return Promise.resolve({ data: mockMembers });
      }
      if (url.includes('/groups/') || url.includes('/groups')) {
        return Promise.resolve({ data: mockGroups });
      }
      if (url.includes('/users/all')) {
        return Promise.resolve({ data: mockUsers });
      }
      return Promise.resolve({ data: [] });
    });
  });

  test('shows loading state initially', () => {
    mockedAxios.get.mockReturnValue(new Promise(() => {}));
    render(<GroupManager />);
    expect(screen.getByText('Loading groups...')).toBeInTheDocument();
  });

  test('renders group list after loading', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('Analysts')).toBeInTheDocument();
    });
    // 'Default' appears both as group name and badge
    const defaultTexts = screen.getAllByText('Default');
    expect(defaultTexts.length).toBeGreaterThanOrEqual(1);
  });

  test('shows Default badge on default group', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      const badge = document.querySelector('.badge-default');
      expect(badge).toBeTruthy();
      expect(badge?.textContent).toBe('Default');
    });
  });

  test('auto-selects default group on load', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      // Default group should be auto-selected, showing the detail panel
      expect(screen.getByText('Dataset Access')).toBeInTheDocument();
    });
  });

  test('shows delete button only for non-default groups', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('Analysts')).toBeInTheDocument();
    });
    // Only one Delete button (for Analysts, not for Default)
    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    expect(deleteButtons).toHaveLength(1);
  });

  test('shows dataset checkboxes for selected group', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('Dataset Access')).toBeInTheDocument();
    });
    // All three datasources should be shown as checkboxes
    expect(screen.getByText('UNEG')).toBeInTheDocument();
    expect(screen.getByText('ACLED')).toBeInTheDocument();
    expect(screen.getByText('OCHA')).toBeInTheDocument();
  });

  test('shows member list for selected group', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('alice@test.com')).toBeInTheDocument();
    });
  });

  test('shows create group form', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText('New group name')).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText('Description (optional)')).toBeInTheDocument();
  });

  test('creates a new group', async () => {
    mockedAxios.post.mockResolvedValue({ data: {} });
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText('New group name')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText('New group name'), {
      target: { value: 'New Team' },
    });
    fireEvent.click(screen.getByText('Create'));

    await waitFor(() => {
      expect(mockedAxios.post).toHaveBeenCalledWith('/api/groups/', {
        name: 'New Team',
        description: null,
      });
    });
  });

  test('opens delete confirmation modal', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('Analysts')).toBeInTheDocument();
    });

    const deleteBtn = screen.getByRole('button', { name: 'Delete' });
    fireEvent.click(deleteBtn);

    // "Delete Group" appears in both the h3 title and the confirm button
    const deleteGroupElements = screen.getAllByText('Delete Group');
    expect(deleteGroupElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Delete the group "Analysts"/)).toBeInTheDocument();
  });

  test('shows error on fetch failure', async () => {
    mockedAxios.get.mockRejectedValue(new Error('Network error'));
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load groups')).toBeInTheDocument();
    });
  });

  test('shows add member dropdown', async () => {
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('Select a user to add...')).toBeInTheDocument();
    });
  });

  test('remove member button calls API', async () => {
    mockedAxios.delete.mockResolvedValue({});
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('alice@test.com')).toBeInTheDocument();
    });

    const removeBtn = screen.getByText('Remove');
    fireEvent.click(removeBtn);

    await waitFor(() => {
      expect(mockedAxios.delete).toHaveBeenCalledWith(
        expect.stringContaining('/members/user-1')
      );
    });
  });

  test('dismisses error on close click', async () => {
    mockedAxios.get.mockRejectedValue(new Error('fail'));
    render(<GroupManager />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load groups')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('×'));
    expect(screen.queryByText('Failed to load groups')).not.toBeInTheDocument();
  });
});
