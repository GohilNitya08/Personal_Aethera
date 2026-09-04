const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1';
const TOKEN_KEY = 'aethera.accessToken';
const REFRESH_TOKEN_KEY = 'aethera.refreshToken';

export const authStore = {
  get token() { return localStorage.getItem(TOKEN_KEY); },
  set(tokens) {
    localStorage.setItem(TOKEN_KEY, tokens.access_token);
    if (tokens.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
  },
  clear() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(REFRESH_TOKEN_KEY); },
};

async function request(path, options = {}) {
  const headers = { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers };
  if (authStore.token) headers.Authorization = `Bearer ${authStore.token}`;
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (response.status === 401) {
    authStore.clear();
    window.dispatchEvent(new Event('aethera:unauthorized'));
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
  return data;
}

const json = (method, payload) => ({ method, body: JSON.stringify(payload) });

export const api = {
  login: (payload) => request('/auth/login', json('POST', payload)),
  forgotPassword: (payload) => request('/auth/forgot-password', json('POST', payload)),
  verifyResetOtp: (payload) => request('/auth/verify-reset-otp', json('POST', payload)),
  resetPassword: (payload) => request('/auth/reset-password', json('POST', payload)),
  exchangeGoogleOAuthCode: (code) => request('/auth/google/exchange', json('POST', { code })),
  register: (payload) => request('/auth/register', json('POST', payload)),
  emailAvailability: (email) => request(`/auth/email-availability?email=${encodeURIComponent(email)}`),
  verifyEmail: (payload) => request('/auth/verify-email', json('POST', payload)),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/users/me'),
  updateMe: (payload) => request('/users/me', json('PUT', payload)),
  workspaces: () => request('/workspaces'),
  workspace: (id) => request(`/workspaces/${id}`),
  workspaceMembers: (id) => request(`/workspaces/${id}/members`),
  addWorkspaceMember: (id, payload) => request(`/workspaces/${id}/invitations`, json('POST', payload)),
  updateWorkspaceMember: (id, memberUserId, payload) => request(`/workspaces/${id}/members/${memberUserId}`, json('PUT', payload)),
  removeWorkspaceMember: (id, memberUserId) => request(`/workspaces/${id}/members/${memberUserId}`, { method: 'DELETE' }),
  transferWorkspaceOwnership: (id, payload) => request(`/workspaces/${id}/transfer-ownership`, json('POST', payload)),
  searchUsers: (q, limit = 20) => request(`/users/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  user: (id) => request(`/users/${id}`),
  createWorkspace: (payload) => request('/workspaces', json('POST', payload)),
  folders: (workspaceId) => request(`/workspaces/${workspaceId}/folders`),
  folderTree: (workspaceId) => request(`/workspaces/${workspaceId}/tree`),
  createFolder: (payload) => request('/folders', json('POST', payload)),
  files: (folderId) => request(`/folders/${folderId}/files`),
  uploadFile: (folderId, file) => { const body = new FormData(); body.append('upload', file); return request(`/folders/${folderId}/files/upload`, { method: 'POST', body }); },
  file: (id) => request(`/files/${id}`),
  shares: () => request('/shares'),
  createShare: (payload) => request('/shares', json('POST', payload)),
  updateShare: (id, payload) => request(`/shares/${id}`, json('PUT', payload)),
  revokeShare: (id) => request(`/shares/${id}/revoke`, { method: 'POST' }),
};

export { API_BASE_URL };
