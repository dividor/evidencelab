import { useSyncExternalStore } from 'react';

const keys = ['page', 'group', 'settings', 'testing', 'dataset', 'experiment', 'mode', 'check'] as const;
type AdminLocation = Partial<Record<typeof keys[number], string>>;
const locationChange = 'admin-location-change';

function subscribe(callback: () => void) {
  window.addEventListener('popstate', callback);
  window.addEventListener(locationChange, callback);
  return () => {
    window.removeEventListener('popstate', callback);
    window.removeEventListener(locationChange, callback);
  };
}

export function useAdminLocation(): AdminLocation {
  const search = useSyncExternalStore(subscribe, () => window.location.search);
  const params = new URLSearchParams(search);
  const location: AdminLocation = {};
  for (const key of keys) {
    const value = params.get('admin_' + key);
    if (value && /^[a-zA-Z0-9_-]+$/.test(value)) location[key] = value;
  }
  return location;
}

/** Replace only Admin's parameters, leaving the rest of this app URL intact. */
export function openAdminLocation(location: AdminLocation) {
  const url = new URL(window.location.href);
  for (const key of keys) {
    const value = location[key];
    if (value) url.searchParams.set('admin_' + key, value);
    else url.searchParams.delete('admin_' + key);
  }
  if (url.href === window.location.href) return;
  window.history.pushState(null, '', url);
  window.dispatchEvent(new Event(locationChange));
}

/** Older Admin links could retain the path of the previously open Brief. */
export function restoreAdminPath() {
  const url = new URL(window.location.href);
  if (!url.searchParams.has('admin_page')) return;
  const path = url.pathname.replace(/\/brief\/[0-9a-f-]{36}\/?$/i, '/admin');
  if (path === url.pathname) return;
  url.pathname = path;
  window.history.replaceState(window.history.state, '', url);
}
