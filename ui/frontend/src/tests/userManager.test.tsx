import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

// Mock config
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
}));

// Mock useAuth
jest.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'admin-1', email: 'admin@test.com', is_superuser: true },
  }),
}));

// Mock axios — note: `delete` is a JS keyword so jest.mock doesn't auto-mock it.
// We manually set it up.
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;
// Ensure delete is a mock function
if (!mockedAxios.delete) {
  (mockedAxios as any).delete = jest.fn();
}

import UserManager from '../components/admin/UserManager';

const mockUsers = [
  {
    id: 'user-1',
    email: 'alice@test.com',
    display_name: 'Alice',
    is_active: true,
    is_verified: true,
    is_superuser: false,
    created_at: '2024-01-01',
    updated_at: '2024-01-01',
  },
  {
    id: 'admin-1',
    email: 'admin@test.com',
    display_name: 'Admin',
    is_active: true,
    is_verified: true,
    is_superuser: true,
    created_at: '2024-01-01',
    updated_at: '2024-01-01',
  },
];

describe('UserManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAxios.get.mockResolvedValue({ data: mockUsers });
  });

  test('shows loading state initially', () => {
    // Don't resolve the promise immediately
    mockedAxios.get.mockReturnValue(new Promise(() => {}));
    render(<UserManager />);
    expect(screen.getByText('Loading users...')).toBeInTheDocument();
  });

  test('renders user list after loading', async () => {
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('alice@test.com')).toBeInTheDocument();
    });
    expect(screen.getByText('admin@test.com')).toBeInTheDocument();
  });

  test('displays user count', async () => {
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('2 users')).toBeInTheDocument();
    });
  });

  test('displays display names', async () => {
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument();
    });
  });

  test('shows delete button for non-current users only', async () => {
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('alice@test.com')).toBeInTheDocument();
    });
    // Should have exactly one delete button (for alice, not for current admin)
    const deleteButtons = screen.getAllByText('Delete');
    expect(deleteButtons).toHaveLength(1);
  });

  test('shows error message on fetch failure', async () => {
    mockedAxios.get.mockRejectedValue(new Error('Network error'));
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load users')).toBeInTheDocument();
    });
  });

  test('opens confirm modal on delete click', async () => {
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('alice@test.com')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Delete'));
    // The modal title appears in an h3, the confirm button also says "Delete User"
    const deleteUserElements = screen.getAllByText('Delete User');
    expect(deleteUserElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Permanently delete alice@test.com/)).toBeInTheDocument();
  });

  test('calls delete API and refreshes on confirm', async () => {
    mockedAxios.delete.mockResolvedValue({});
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('alice@test.com')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Delete'));
    // Click the confirm button in the modal (the btn-danger one)
    const confirmBtn = document.querySelector('.confirm-modal-actions .btn-danger') as HTMLElement;
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockedAxios.delete).toHaveBeenCalledWith('/api/users/user-1');
    });
  });

  test('toggles user flag via API', async () => {
    mockedAxios.patch.mockResolvedValue({});
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('alice@test.com')).toBeInTheDocument();
    });

    // Find checkboxes in alice's row
    const rows = document.querySelectorAll('tbody tr');
    const aliceRow = rows[0];
    const checkboxes = aliceRow.querySelectorAll('input[type="checkbox"]');
    // Active checkbox (first one) should be checked
    expect((checkboxes[0] as HTMLInputElement).checked).toBe(true);

    fireEvent.click(checkboxes[0]);
    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith(
        '/api/users/user-1/flags',
        null,
        { params: { is_active: false } }
      );
    });
  });

  test('dismisses error on close click', async () => {
    mockedAxios.get.mockRejectedValue(new Error('fail'));
    render(<UserManager />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load users')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('×'));
    expect(screen.queryByText('Failed to load users')).not.toBeInTheDocument();
  });
});
