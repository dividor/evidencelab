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

jest.mock('../components/admin/GroupSettingsManager', () => {
  return function MockGroupSettingsManager() {
    return <div data-testid="group-settings-manager">GroupSettingsManager</div>;
  };
});

jest.mock('../components/admin/TestingManager', () => {
  return function MockTestingManager() {
    return <div data-testid="testing-manager">TestingManager</div>;
  };
});

import { restoreAdminPath } from '../utils/adminLocation';
import AdminPanel from '../components/admin/AdminPanel';

describe('AdminPanel', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/admin');
    jest.clearAllMocks();
    mockUseAuth.mockReturnValue({
      user: { id: '1', email: 'admin@test.com', is_superuser: true },
    });
  });

  test('repairs a saved Admin URL with a Brief path and preserves ordinary share links', () => {
    const brief = '/lab/brief/8518906e-6c45-4033-b696-904eea1916f5';
    window.history.replaceState(null, '', brief);
    restoreAdminPath();
    expect(window.location.pathname).toBe(brief);
    const query = '?admin_page=testing&admin_testing=experiments';
    window.history.replaceState(null, '', brief + query);
    restoreAdminPath();
    expect(window.location.pathname + window.location.search).toBe('/lab/admin' + query);
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

  test('switches to Group Settings tab on click', () => {
    render(<AdminPanel isActive={true} />);
    fireEvent.click(screen.getByText('Group Settings'));
    expect(screen.getByTestId('group-settings-manager')).toBeInTheDocument();
    expect(screen.queryByTestId('user-manager')).not.toBeInTheDocument();
    expect(screen.queryByTestId('group-manager')).not.toBeInTheDocument();
  });

  test('switches to Testing tab on click (admin-only harness)', () => {
    render(<AdminPanel isActive={true} />);
    fireEvent.click(screen.getByText('Testing (Experiments)'));
    expect(screen.getByTestId('testing-manager')).toBeInTheDocument();
    expect(screen.queryByTestId('user-manager')).not.toBeInTheDocument();
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

test('refresh and history restore the Admin page while preserving other URL settings', () => {
  mockUseAuth.mockReturnValue({ user: { is_superuser: true } });
  window.history.replaceState(null, '', '/admin?dataset=library#section');
  const screenBeforeRefresh = render(<AdminPanel isActive />);
  fireEvent.click(screen.getByText('Group Settings'));
  const saved = window.location.href;
  expect(saved).toContain('dataset=library');
  expect(saved).toContain('admin_page=group-settings');
  expect(window.location.hash).toBe('#section');
  screenBeforeRefresh.unmount();
  render(<AdminPanel isActive />);
  expect(screen.getByTestId('group-settings-manager')).toBeVisible();
  fireEvent.click(screen.getByText('Testing (Experiments)'));
  window.history.replaceState(null, '', saved);
  fireEvent.popState(window);
  expect(screen.getByTestId('group-settings-manager')).toBeVisible();
});
