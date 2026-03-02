import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

// Mock config module before importing component
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  USER_MODULE: true,
}));

// Mock useAuth hook
const mockUseAuth = jest.fn();
jest.mock('../hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

// Mock child components
jest.mock('../components/admin/UserManager', () => {
  return function MockUserManager() {
    return <div data-testid="user-manager">UserManager</div>;
  };
});

jest.mock('../components/admin/GroupManager', () => {
  return function MockGroupManager() {
    return <div data-testid="group-manager">GroupManager</div>;
  };
});

import AdminPanel from '../components/admin/AdminPanel';

describe('AdminPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseAuth.mockReturnValue({
      user: { id: '1', email: 'admin@test.com', is_superuser: true },
    });
  });

  test('renders when active and user is superuser', () => {
    render(<AdminPanel isActive={true} />);
    expect(screen.getByText('Administration')).toBeInTheDocument();
  });

  test('returns null when not active', () => {
    const { container } = render(<AdminPanel isActive={false} />);
    expect(container.innerHTML).toBe('');
  });

  test('returns null when user is not superuser', () => {
    mockUseAuth.mockReturnValue({
      user: { id: '1', email: 'user@test.com', is_superuser: false },
    });
    const { container } = render(<AdminPanel isActive={true} />);
    expect(container.innerHTML).toBe('');
  });

  test('returns null when user is null', () => {
    mockUseAuth.mockReturnValue({ user: null });
    const { container } = render(<AdminPanel isActive={true} />);
    expect(container.innerHTML).toBe('');
  });

  test('shows Users tab by default', () => {
    render(<AdminPanel isActive={true} />);
    expect(screen.getByTestId('user-manager')).toBeInTheDocument();
    expect(screen.queryByTestId('group-manager')).not.toBeInTheDocument();
  });

  test('switches to Groups tab on click', () => {
    render(<AdminPanel isActive={true} />);
    fireEvent.click(screen.getByText('Groups'));
    expect(screen.getByTestId('group-manager')).toBeInTheDocument();
    expect(screen.queryByTestId('user-manager')).not.toBeInTheDocument();
  });

  test('switches back to Users tab on click', () => {
    render(<AdminPanel isActive={true} />);
    fireEvent.click(screen.getByText('Groups'));
    fireEvent.click(screen.getByText('Users'));
    expect(screen.getByTestId('user-manager')).toBeInTheDocument();
    expect(screen.queryByTestId('group-manager')).not.toBeInTheDocument();
  });

  test('has active class on selected tab', () => {
    render(<AdminPanel isActive={true} />);
    const usersTab = screen.getByText('Users');
    expect(usersTab.className).toContain('admin-tab-active');

    fireEvent.click(screen.getByText('Groups'));
    const groupsTab = screen.getByText('Groups');
    expect(groupsTab.className).toContain('admin-tab-active');
    expect(usersTab.className).not.toContain('admin-tab-active');
  });
});
