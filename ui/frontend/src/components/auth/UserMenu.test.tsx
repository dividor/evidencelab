import React from 'react';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import axios from 'axios';
import UserMenu from './UserMenu';
import { AuthContext } from '../../hooks/useAuth';
import type { AuthContextValue } from '../../types/auth';

jest.mock('axios');

const ALICE_EMAIL = 'alice@example.com';
const ALICE_NAME = 'Alice Baker';

const mockAuthValue = (overrides: Partial<AuthContextValue> = {}): AuthContextValue => ({
  user: null,
  token: null,
  isLoading: false,
  isAuthenticated: false,
  login: jest.fn(),
  register: jest.fn(),
  logout: jest.fn(),
  refreshUser: jest.fn(),
  sessionExpired: false,
  verificationMessage: null,
  clearVerificationMessage: jest.fn(),
  resetPasswordToken: null,
  clearResetPasswordToken: jest.fn(),
  ...overrides,
});

const renderWithAuth = (authValue: AuthContextValue, props = {}) =>
  render(
    <AuthContext.Provider value={authValue}>
      <UserMenu {...props} />
    </AuthContext.Provider>
  );

describe('UserMenu', () => {
  it('renders nothing while loading', () => {
    const { container } = renderWithAuth(mockAuthValue({ isLoading: true }));
    expect(container.firstChild).toBeNull();
  });

  it('renders sign-in button when not authenticated', () => {
    renderWithAuth(mockAuthValue());
    const button = screen.getByTitle('Sign in');
    expect(button).toBeInTheDocument();
  });

  it('renders user initials when authenticated', () => {
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: ALICE_EMAIL,
          first_name: 'Alice',
          last_name: 'Baker',
          display_name: ALICE_NAME,
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      })
    );
    // Should show initials "AB"
    expect(screen.getByText('AB')).toBeInTheDocument();
  });

  it('shows dropdown menu on click', () => {
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: ALICE_EMAIL,
          first_name: 'Alice',
          last_name: 'Baker',
          display_name: ALICE_NAME,
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      })
    );
    fireEvent.click(screen.getByText('AB'));
    expect(screen.getByText('Profile')).toBeInTheDocument();
    expect(screen.getByText('Sign Out')).toBeInTheDocument();
  });

  it('shows Admin option for superusers', () => {
    const onAdminClick = jest.fn();
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: 'admin@example.com',
          first_name: 'Super',
          last_name: 'User',
          display_name: 'Super User',
          is_active: true,
          is_verified: true,
          is_superuser: true,
          created_at: null,
          updated_at: null,
        },
      }),
      { onAdminClick }
    );
    fireEvent.click(screen.getByText('SU'));
    expect(screen.getByRole('button', { name: 'Admin' })).toBeInTheDocument();
  });

  it('does not show Admin for non-superusers', () => {
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: 'user@example.com',
          first_name: 'User',
          last_name: null,
          display_name: 'User',
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      }),
      { onAdminClick: jest.fn() }
    );
    fireEvent.click(screen.getByText('U'));
    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
  });

  it('calls logout on Sign Out click', () => {
    const logout = jest.fn();
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        logout,
        user: {
          id: '1',
          email: ALICE_EMAIL,
          first_name: 'Alice',
          last_name: null,
          display_name: 'Alice',
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      })
    );
    fireEvent.click(screen.getByText('A'));
    fireEvent.click(screen.getByText('Sign Out'));
    expect(logout).toHaveBeenCalled();
  });

  describe('Environmental impact', () => {
    const label = 'Environmental impact';
    const signedIn = () => mockAuthValue({
      isAuthenticated: true,
      user: {
        id: '1',
        email: ALICE_EMAIL,
        first_name: 'Alice',
        last_name: 'Baker',
        display_name: ALICE_NAME,
        is_active: true,
        is_verified: true,
        is_superuser: false,
        created_at: null,
        updated_at: null,
      },
    });
    const emptySummary = {
      from_date: '2026-05-01',
      to_date: '2026-05-30',
      completion_tokens: 0,
      footprint_unestimated_tokens: 0,
      energy_kwh_min: null,
      energy_kwh_max: null,
      gwp_kgco2eq_min: null,
      gwp_kgco2eq_max: null,
      water_l_min: null,
      water_l_max: null,
    };
    const openImpact = () => {
      renderWithAuth(signedIn(), { personalImpactEnabled: true });
      fireEvent.click(screen.getByText('AB'));
      fireEvent.click(screen.getByRole('button', { name: label }));
      return within(screen.getByRole('dialog', { name: label }));
    };

    beforeAll(() => {
      Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
        configurable: true,
        value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
      });
    });

    it('does not show the menu item for an account with access off', () => {
      renderWithAuth(signedIn(), { personalImpactEnabled: false });
      fireEvent.click(screen.getByText('AB'));
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument();
    });

    it('shows the past 30 days first and loads the year to date when selected', async () => {
      const get = axios.get as jest.Mock;
      get.mockResolvedValueOnce({ data: {
        ...emptySummary,
        completion_tokens: 100,
        energy_kwh_min: 0.001,
        energy_kwh_max: 0.002,
        footprint_unestimated_tokens: 20,
      } }).mockResolvedValueOnce({ data: {
        ...emptySummary,
        from_date: '2026-01-01',
        completion_tokens: 200,
        energy_kwh_min: 0.003,
        energy_kwh_max: 0.004,
      } });

      const dialog = openImpact();
      expect(dialog.getByRole('status')).toHaveTextContent('Loading');
      expect(dialog.getByRole('button', { name: 'Last 30 days' })).toHaveAttribute('aria-pressed', 'true');
      expect(await dialog.findByText('1–2')).toBeInTheDocument();
      expect(dialog.getByText(/leave out 20 of 100 output tokens/)).toBeInTheDocument();
      expect(get).toHaveBeenLastCalledWith(
        '/api/llm-usage/me/footprint', expect.objectContaining({ params: { period: '30-days' } }),
      );

      fireEvent.click(dialog.getByRole('button', { name: 'Year to date' }));
      expect(await dialog.findByText('3–4')).toBeInTheDocument();
      expect(dialog.getByText(/Jan 1, 2026/)).toBeInTheDocument();
      expect(dialog.queryByText('1–2')).not.toBeInTheDocument();
      expect(get).toHaveBeenLastCalledWith(
        '/api/llm-usage/me/footprint', expect.objectContaining({ params: { period: 'year-to-date' } }),
      );
      fireEvent.click(dialog.getByRole('button', { name: 'Close' }));
      expect(screen.queryByRole('dialog', { name: label })).not.toBeInTheDocument();
    });

    it('describes an empty period without displaying zero estimates', async () => {
      (axios.get as jest.Mock).mockResolvedValueOnce({ data: emptySummary });
      const dialog = openImpact();
      expect(await dialog.findByText(/No text generation was recorded/)).toBeInTheDocument();
      expect(dialog.queryByText('Energy (Wh)')).not.toBeInTheDocument();
    });

    it('reports a summary request failure', async () => {
      (axios.get as jest.Mock).mockRejectedValueOnce(new Error('Request failed'));
      const dialog = openImpact();
      expect(await dialog.findByRole('alert')).toHaveTextContent('Couldn’t load your environmental impact');
    });
  });

  describe('menu item clicks survive the trigger losing focus', () => {
    const signedInAdmin = () =>
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: ALICE_EMAIL,
          first_name: 'Alice',
          last_name: 'Baker',
          display_name: ALICE_NAME,
          is_active: true,
          is_verified: true,
          is_superuser: true,
          created_at: null,
          updated_at: null,
        },
      });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('opens Saved Research when the click lands long after focus left the trigger', async () => {
      jest.useFakeTimers();
      (axios.get as jest.Mock).mockResolvedValue({ data: [] });
      renderWithAuth(signedInAdmin(), { onLoadResearch: jest.fn() });
      const trigger = screen.getByText('AB');
      fireEvent.click(trigger);
      const item = screen.getByText('Saved Research');
      // A real click moves focus off the trigger on mouse-down; the mouse-up
      // (and so the click) can arrive much later on a slow click or a remote
      // desktop. The item must still be there when it does.
      fireEvent.mouseDown(item);
      fireEvent.focusOut(trigger);
      act(() => {
        jest.advanceTimersByTime(1000);
      });
      fireEvent.click(item);
      expect(screen.getByText('Load Previous Research')).toBeInTheDocument();
      await act(async () => {
        for (let i = 0; i < 5; i++) await Promise.resolve();
      });
    });

    it('opens Admin when the click lands long after focus left the trigger', () => {
      jest.useFakeTimers();
      const onAdminClick = jest.fn();
      renderWithAuth(signedInAdmin(), { onAdminClick });
      const trigger = screen.getByText('AB');
      fireEvent.click(trigger);
      const item = screen.getByRole('button', { name: 'Admin' });
      fireEvent.mouseDown(item);
      fireEvent.focusOut(trigger);
      act(() => {
        jest.advanceTimersByTime(1000);
      });
      fireEvent.click(item);
      expect(onAdminClick).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('button', { name: 'Admin' })).not.toBeInTheDocument();
    });

    it('closes when the user presses outside the menu', () => {
      renderWithAuth(signedInAdmin());
      fireEvent.click(screen.getByText('AB'));
      expect(screen.getByText('Profile')).toBeInTheDocument();
      fireEvent.mouseDown(document.body);
      expect(screen.queryByText('Profile')).not.toBeInTheDocument();
    });

    it('closes on Escape', () => {
      renderWithAuth(signedInAdmin());
      fireEvent.click(screen.getByText('AB'));
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.queryByText('Profile')).not.toBeInTheDocument();
    });
  });
});
