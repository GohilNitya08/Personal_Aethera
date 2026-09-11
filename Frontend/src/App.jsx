import { useCallback, useEffect, useRef, useState } from 'react';
import { api, authStore, API_BASE_URL } from './services/api';

const navItems = [['dashboard', 'Dashboard'], ['workspaces', 'Workspaces'], ['search', 'Search workspaces'], ['shared', 'Shared files'], ['profile', 'Profile & settings']];
const formatBytes = (bytes = 0) => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : bytes < 1073741824 ? `${(bytes / 1048576).toFixed(1)} MB` : `${(bytes / 1073741824).toFixed(1)} GB`;
const formatDate = (value) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value)) : '—';

function useAsync(task, dependencies = []) {
  const [state, setState] = useState({ loading: true, data: null, error: '' });
  const run = useCallback(async () => {
    setState((old) => ({ ...old, loading: true, error: '' }));
    try { setState({ loading: false, data: await task(), error: '' }); }
    catch (error) { setState({ loading: false, data: null, error: error.message }); }
  }, dependencies);
  useEffect(() => { run(); }, [run]);
  return { ...state, reload: run };
}

function AuthScreen({ onAuthenticated, oauthError }) {
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ email: '', password: '', username: '', full_name: '', challenge: '', otp: '', reset_token: '', new_password: '' });
  const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const [emailStatus, setEmailStatus] = useState('');
  useEffect(() => {
    if (mode !== 'register') return undefined;
    const email = form.email.trim();
    setEmailStatus('');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return undefined;
    setEmailStatus('checking');
    const timer = setTimeout(async () => {
      try { setEmailStatus((await api.emailAvailability(email)).available ? 'available' : 'registered'); }
      catch { setEmailStatus(''); }
    }, 450);
    return () => clearTimeout(timer);
  }, [form.email, mode]);
  const submit = async (event) => {
    event.preventDefault(); setError(''); setLoading(true);
    try {
      if (mode === 'register') { const result = await api.register({ email: form.email, password: form.password, username: form.username, full_name: form.full_name }); setForm({ ...form, challenge: result.challenge, otp: '' }); setMode('email-verify'); setError(result.message); }
      else if (mode === 'forgot') { const res = await api.forgotPassword({ email: form.email }); setForm({ ...form, challenge: res.challenge }); setMode('verify'); setError(res.message || 'If an account exists, a reset code was sent.'); }
      else if (mode === 'verify') { const result = await api.verifyResetOtp({ challenge: form.challenge, otp: form.otp }); setForm({ ...form, reset_token: result.reset_token }); setMode('reset'); setError('Code verified. Choose a new password.'); }
      else if (mode === 'email-verify') { await api.verifyEmail({ challenge: form.challenge, otp: form.otp }); setMode('login'); setForm({ ...form, password: '' }); setError('Email verified. Sign in to continue.'); }
      else if (mode === 'reset') { await api.resetPassword({ reset_token: form.reset_token, new_password: form.new_password }); setMode('login'); setForm({ ...form, password: '', new_password: '' }); setError('Password reset. Sign in to continue.'); }
      else { const tokens = await api.login({ email: form.email, password: form.password }); authStore.set(tokens); onAuthenticated(); }
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };
  const isRegister = mode === 'register';
  const frontMode = isRegister ? 'login' : mode;
  const frontTitle = frontMode === 'login' ? 'Sign in' : frontMode === 'forgot' ? 'Reset your password' : frontMode === 'verify' || frontMode === 'email-verify' ? 'Enter your code' : 'Choose a new password';
  const frontMuted = frontMode === 'login' ? 'Continue to your secure workspace.' : frontMode === 'email-verify' ? 'Enter the code sent to your email address.' : 'Secure account recovery for AETHERA.';
  const frontCta = loading ? 'Please wait…' : frontMode === 'login' ? 'Sign in' : frontMode === 'forgot' ? 'Send reset code' : frontMode === 'verify' || frontMode === 'email-verify' ? 'Verify code' : 'Reset password';
  const goRegister = () => { setMode('register'); setError(''); };
  const goLogin = () => { setMode('login'); setError(''); };

  return (
    <main className="auth-shell">
      <section className="auth-intro">
        <div className="brand"><span>✦</span> AETHERA</div>
        <div>
          <p className="eyebrow">PRIVATE BY DESIGN</p>
          <h1>Your work,<br />calmly organized.</h1>
          <p>Secure, intelligent storage and collaboration for the things that matter.</p>
        </div>
        <div className="intro-card"><span>◈</span><p>One place for your documents, projects, and shared workspaces.</p></div>
      </section>
      <section className="auth-panel">
        <div className={`auth-scene${isRegister ? ' is-flipped' : ''}`}>
          <div className="auth-flip">
            <form onSubmit={submit} className="auth-card auth-face auth-face-front" aria-hidden={isRegister}>
              <p className="eyebrow">WELCOME TO AETHERA</p>
              <h2>{frontTitle}</h2>
              <p className="muted">{frontMuted}</p>
              {(oauthError || (!isRegister && error)) && <div className="notice">{oauthError || error}</div>}
              {['login', 'forgot'].includes(frontMode) && <Field label="Email address" type="email" value={form.email} onChange={(email) => setForm({ ...form, email })} required={!isRegister} />}
              {frontMode === 'login' && <Field label="Password" type="password" value={form.password} onChange={(password) => setForm({ ...form, password })} required={!isRegister} minLength={1} />}
              {(frontMode === 'verify' || frontMode === 'email-verify') && <Field label="6-digit code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={form.otp} onChange={(otp) => setForm({ ...form, otp })} required={!isRegister} />}
              {frontMode === 'reset' && <Field label="New password" type="password" value={form.new_password} onChange={(new_password) => setForm({ ...form, new_password })} required={!isRegister} minLength={8} />}
              <button className="button primary" disabled={loading || isRegister}>{frontCta}</button>
              {frontMode === 'login' && (
                <>
                  <div className="divider"><span>or</span></div>
                  <a className="button google" href={`${API_BASE_URL}/auth/google/login`} tabIndex={isRegister ? -1 : undefined}><b>G</b> Continue with Google</a>
                  <p className="switch"><button type="button" onClick={() => { setMode('forgot'); setError(''); }} tabIndex={isRegister ? -1 : undefined}>Forgot password?</button></p>
                </>
              )}
              <p className="switch">
                <button type="button" onClick={frontMode === 'login' ? goRegister : goLogin} tabIndex={isRegister ? -1 : undefined}>
                  {frontMode === 'login' ? 'Create an account' : 'Back to sign in'}
                </button>
              </p>
            </form>

            <form onSubmit={submit} className="auth-card auth-face auth-face-back" aria-hidden={!isRegister}>
              <p className="eyebrow">WELCOME TO AETHERA</p>
              <h2>Create your account</h2>
              <p className="muted">Join AETHERA with a secure personal account.</p>
              {isRegister && error && <div className="notice">{error}</div>}
              <Field label="Email address" type="email" value={form.email} onChange={(email) => setForm({ ...form, email })} required={isRegister} />
              {emailStatus && <small className={`email-status ${emailStatus}`}>{emailStatus === 'checking' ? 'Checking...' : emailStatus === 'available' ? 'Email available' : 'Email already registered'}</small>}
              <Field label="Full name" value={form.full_name} onChange={(full_name) => setForm({ ...form, full_name })} required={isRegister} />
              <Field label="Username" value={form.username} onChange={(username) => setForm({ ...form, username })} required={isRegister} />
              <Field label="Password" type="password" value={form.password} onChange={(password) => setForm({ ...form, password })} required={isRegister} minLength={8} />
              <button className="button primary" disabled={loading || !isRegister || emailStatus !== 'available'}>{loading ? 'Please wait…' : 'Create account'}</button>
              <p className="switch"><button type="button" onClick={goLogin} tabIndex={!isRegister ? -1 : undefined}>Back to sign in</button></p>
            </form>
          </div>
        </div>
      </section>
    </main>
  );
}

function Field({ label, onChange, ...props }) { return <label className="field"><span>{label}</span><input onChange={(e) => onChange(e.target.value)} {...props} /></label>; }
function Empty({ title, body, action }) { return <div className="empty"><div>◇</div><h3>{title}</h3><p>{body}</p>{action}</div>; }
function ErrorState({ message, retry }) { return <div className="notice"><b>Couldn’t load this view.</b><br />{message} {retry && <button onClick={retry}>Try again</button>}</div>; }

function NotificationBellIcon() { return <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>; }
function timeAgo(dateStr) { if (!dateStr) return ''; const s = (Date.now() - new Date(dateStr).getTime()) / 1000; if (s < 60) return 'Just now'; if (s < 3600) return `${Math.floor(s / 60)}m ago`; if (s < 86400) return `${Math.floor(s / 3600)}h ago`; if (s < 604800) return `${Math.floor(s / 86400)}d ago`; return formatDate(dateStr); }
function AppShell({ page, setPage, onLogout, children, user }) { const notifications = useAsync(api.notifications, []); const [open, setOpen] = useState(false); const wrapRef = useRef(null); const inbox = notifications.data; const markRead = async (item) => { if (!item.is_read) { try { await api.markNotificationRead(item.notification_id); } catch (_) {} notifications.reload(); } }; const markAll = async () => { try { await api.markAllNotificationsRead(); } catch (_) {} notifications.reload(); };
  useEffect(() => { if (!open) return undefined; const handler = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); }; document.addEventListener('mousedown', handler); return () => document.removeEventListener('mousedown', handler); }, [open]);
  return <div className="app-shell"><aside><div className="brand"><span>✦</span> AETHERA</div><p className="workspace-label">WORKSPACE</p><nav>{navItems.map(([id, label]) => <button className={page === id ? 'active' : ''} onClick={() => setPage(id)} key={id}><span>{id === 'dashboard' ? '⌂' : id === 'workspaces' ? '▦' : id === 'search' ? '⚲' : id === 'shared' ? '↗' : '◎'}</span>{label}</button>)}</nav><div className="sidebar-bottom"><div className="user-chip"><div>{user?.full_name?.slice(0, 1) || 'A'}</div><span>{user?.full_name || 'Loading…'}<small>{user?.email || ''}</small></span></div><button className="logout" onClick={onLogout}>↪ Log out</button></div></aside><section className="main-area"><header><div><p className="eyebrow">AETHERA / {page.replace('-', ' ').toUpperCase()}</p><h2>{page === 'workspace' ? 'Workspace' : page === 'search' ? 'Search workspaces' : page === 'shared' ? 'Shared files' : page === 'profile' ? 'Profile & settings' : page[0].toUpperCase() + page.slice(1)}</h2></div><div className="header-actions"><div className="notification-wrap" ref={wrapRef}><button className={`notification-button${open ? ' active' : ''}`} type="button" aria-label="Notifications" onClick={() => setOpen(!open)}><NotificationBellIcon />{inbox?.unread_count > 0 && <b>{inbox.unread_count > 9 ? '9+' : inbox.unread_count}</b>}</button>{open && <div className="notification-popover"><div className="notification-head"><strong>Notifications</strong>{inbox?.unread_count > 0 && <button className="text-button" onClick={markAll}>Mark all as read</button>}</div>{notifications.loading ? <p className="notification-empty muted">Loading…</p> : notifications.error ? <p className="notification-empty notification-error">⚠ Could not load notifications. <button className="text-button" onClick={notifications.reload}>Retry</button></p> : inbox?.notifications?.length ? <div className="notification-list">{inbox.notifications.map((item) => <button className={`notification-item${item.is_read ? '' : ' unread'}`} key={item.notification_id} onClick={() => markRead(item)}>{!item.is_read && <span className="unread-dot" />}<div className="notification-body"><strong>{item.title}</strong><span>{item.message}</span></div><time>{timeAgo(item.created_at)}</time></button>)}</div> : <div className="notification-empty"><span className="notification-empty-icon">🔔</span><p>You're all caught up</p><small className="muted">No notifications yet.</small></div>}</div>}</div><div className="top-status"><span></span> Secure session</div></div></header>{children}</section></div>; }

function Dashboard({ go, user }) { const { data: workspaces, loading, error, reload } = useAsync(api.workspaces, []); const { data: shares } = useAsync(api.shares, []);
  if (error) return <ErrorState message={error} retry={reload} />;
  return <div className="page-content"><section className="hero"><div><p className="eyebrow">YOUR SPACE</p><h1>Good to see you.</h1><p>Pick up where you left off or create a new space for your next project.</p></div><button className="button primary" onClick={() => go('workspaces')}>Manage workspaces</button></section><section className="stat-grid"><Stat label="Workspaces" value={loading ? '—' : workspaces.length} /><Stat label="Shared with you" value={shares?.length ?? '—'} /><StorageStat user={user} /></section><section className="panel"><div className="panel-head"><div><h3>Recent workspaces</h3><p>Spaces you own or collaborate in.</p></div><button className="text-button" onClick={() => go('workspaces')}>View all</button></div>{loading ? <Loading /> : workspaces.length ? <div className="workspace-cards">{workspaces.slice(0, 3).map((workspace) => <WorkspaceCard key={workspace.workspace_id} workspace={workspace} open={() => go('workspace', workspace.workspace_id)} />)}</div> : <Empty title="No workspaces yet" body="Create your first workspace to organize folders and files." action={<button className="button primary" onClick={() => go('workspaces')}>Create workspace</button>} />}</section></div>; }
function Stat({ label, value, detail }) { return <div className="stat"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>; }
function StorageStat({ user }) { const used = user?.storage_used ?? 0; const limit = user?.storage_limit ?? 0; const pct = limit > 0 ? Math.min(100, Math.max(0, (used / limit) * 100)) : 0; return <div className="stat storage-stat"><span>Storage</span><strong>{formatBytes(used)} <small className="storage-of">/ {limit ? formatBytes(limit) : 'Unlimited'}</small></strong><div className="storage-bar"><div className="storage-bar-fill" style={{ width: `${pct}%` }} /></div><small>{limit > 0 ? `${pct < 0.1 && used > 0 ? '<0.1' : pct.toFixed(1)}% used` : 'No limit set'}</small></div>; }
function Loading() { return <div className="loading">Loading real AETHERA data…</div>; }
function WorkspaceCard({ workspace, open }) { return <button className="workspace-card" onClick={open}><span className={`color-dot ${workspace.color}`}></span><div><h4>{workspace.workspace_name}</h4><p>{workspace.description || 'No description yet'}</p></div><small>{workspace.member_role || 'NO MEMBER ROLE'} · {workspace.visibility}</small></button>; }

function Workspaces({ open }) { const { data, loading, error, reload } = useAsync(api.workspaces, []); const [showForm, setShowForm] = useState(false); const [form, setForm] = useState({ workspace_name: '', workspace_type: 'PERSONAL', description: '', visibility: 'PRIVATE', color: 'blue' }); const [message, setMessage] = useState('');
  const create = async (e) => { e.preventDefault(); setMessage(''); try { const workspace = await api.createWorkspace(form); setShowForm(false); open('workspace', workspace.workspace_id); } catch (err) { setMessage(err.message); } };
  return <div className="page-content"><div className="page-actions"><p className="muted">Create spaces for projects, teams, and private work.</p><button className="button primary" onClick={() => setShowForm(!showForm)}>+ New workspace</button></div>{showForm && <form className="inline-form" onSubmit={create}><Field label="Workspace name" value={form.workspace_name} onChange={(workspace_name) => setForm({ ...form, workspace_name })} required /><label className="field"><span>Type</span><select value={form.workspace_type} onChange={(e) => setForm({ ...form, workspace_type: e.target.value })}><option value="PERSONAL">Personal</option><option value="INSTITUTION">Institution</option></select></label><Field label="Description (optional)" value={form.description} onChange={(description) => setForm({ ...form, description })} /><label className="field"><span>Visibility</span><select value={form.visibility} onChange={(e) => setForm({ ...form, visibility: e.target.value })}><option value="PRIVATE">Private</option><option value="SHARED">Shared</option><option value="PUBLIC">Public</option></select></label>{message && <div className="notice">{message}</div>}<button className="button primary">Create workspace</button></form>}{error ? <ErrorState message={error} retry={reload} /> : loading ? <Loading /> : data.length ? <div className="workspace-list">{data.map((workspace) => <WorkspaceCard key={workspace.workspace_id} workspace={workspace} open={() => open('workspace', workspace.workspace_id)} />)}</div> : <Empty title="No workspaces yet" body="Your workspace list is empty in the backend." />}</div>; }

function WorkspaceDetail({ workspaceId, back, go, currentUser }) {
  const { data: workspace, loading, error, reload } = useAsync(() => api.workspace(workspaceId), [workspaceId]);
  const foldersState = useAsync(() => api.folders(workspaceId), [workspaceId]);
  const membersState = useAsync(() => workspace?.member_role ? api.workspaceMembers(workspaceId) : Promise.resolve([]), [workspaceId, workspace?.member_role]);
  const [folderName, setFolderName] = useState('');
  const [notice, setNotice] = useState('');
  const [pendingDeleteFolder, setPendingDeleteFolder] = useState(null);
  const [busyFolderDelete, setBusyFolderDelete] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showMembers, setShowMembers] = useState(false);

  const canDeleteFolder = (fld) => {
    if (workspace?.member_role === 'OWNER' || workspace?.member_role === 'ADMIN') return true;
    if (workspace?.member_role === 'EDITOR' && sameUserId(fld.created_by, currentUser?.user_id)) return true;
    return false;
  };

  const createFolder = async (event) => {
    event.preventDefault();
    try {
      await api.createFolder({ workspace_id: workspaceId, folder_name: folderName, color: 'blue' });
      setFolderName('');
      foldersState.reload();
    } catch (err) {
      setNotice(err.message);
    }
  };

  const confirmDeleteFolder = async () => {
    if (!pendingDeleteFolder) return;
    setBusyFolderDelete(true);
    try {
      await api.deleteFolder(pendingDeleteFolder.folder_id);
      setPendingDeleteFolder(null);
      await foldersState.reload();
    } catch (err) {
      alert(err.message);
    } finally {
      setBusyFolderDelete(false);
    }
  };

  if (error) return <ErrorState message={error} retry={reload} />;
  if (loading) return <Loading />;
  const canWrite = ['OWNER', 'ADMIN', 'EDITOR'].includes(workspace.member_role);
  return (
    <div className="page-content">
      <button className="back" onClick={back}>← All workspaces</button>
      <section className="workspace-header">
        <span className={`big-dot ${workspace.color}`}></span>
        <div>
          <p className="eyebrow">{workspace.workspace_type} · {workspace.visibility} · {workspace.member_role || 'READ-ONLY'}</p>
          <h1>{workspace.workspace_name}</h1>
          <p>{workspace.description || 'No description provided.'}</p>
        </div>
        <div className="storage">
          <span>Storage</span>
          <strong>{formatBytes(workspace.storage_used)} <small>of {workspace.storage_limit ? formatBytes(workspace.storage_limit) : 'unlimited'}</small></strong>
        </div>
        <div className="page-actions" style={{ marginLeft: 'auto' }}>
          {['OWNER', 'ADMIN'].includes(workspace.member_role) && (
            <button className="button secondary" onClick={() => { setShowSettings(true); setShowMembers(false); }}>
              Edit Workspace
            </button>
          )}
          {['OWNER', 'ADMIN', 'EDITOR'].includes(workspace.member_role) && (
            <button className="button secondary" onClick={() => { setShowMembers(true); setShowSettings(false); }}>
              Manage Members
            </button>
          )}
        </div>
      </section>

      {showSettings && ['OWNER', 'ADMIN'].includes(workspace.member_role) && (
        <WorkspaceSettings workspace={workspace} reload={reload} goBack={back} onClose={() => setShowSettings(false)} />
      )}

      {showMembers && ['OWNER', 'ADMIN', 'EDITOR'].includes(workspace.member_role) && (
        <>
          <WorkspaceMembers workspaceId={workspaceId} workspace={workspace} currentUser={currentUser} membersState={membersState} onWorkspaceChanged={reload} onClose={() => setShowMembers(false)} />
          {workspace.member_role === 'OWNER' && <JoinRequestsPanel workspaceId={workspaceId} onMembersChanged={() => membersState.reload()} />}
        </>
      )}

      {(!showSettings && !showMembers) && (
        <section className="panel">
          <div className="panel-head"><div><h3>Folders</h3><p>Open a folder to view its actual files.</p></div></div>
        {canWrite && <form className="compact-form" onSubmit={createFolder}>
          <input placeholder="New folder name" value={folderName} onChange={(e) => setFolderName(e.target.value)} required />
          <button className="button secondary">Add folder</button>
        </form>}
        {notice && <div className="notice">{notice}</div>}
        {foldersState.error ? <ErrorState message={foldersState.error} retry={foldersState.reload} /> : foldersState.loading ? <Loading /> : (foldersState.data || []).filter((item) => !item.parent_folder_id).length ? (
          <div className="folder-grid">{(foldersState.data || []).filter((item) => !item.parent_folder_id).map((folder) => (
            <div className="folder-card" key={folder.folder_id} style={{ position: 'relative' }}>
              <div style={{ position: 'absolute', top: 5, right: 5, display: 'flex', gap: 4 }}>
                {canWrite && (
                  <button
                    type="button"
                    className="text-button"
                    title="Rename folder"
                    onClick={(e) => {
                      e.stopPropagation();
                      const nn = window.prompt('New folder name:', folder.folder_name);
                      if (nn && nn !== folder.folder_name) {
                        api.updateFolder(folder.folder_id, { folder_name: nn })
                          .then(() => foldersState.reload())
                          .catch(err => alert(err.message));
                      }
                    }}
                  >
                    ✎
                  </button>
                )}
                {canDeleteFolder(folder) && (
                  <button
                    type="button"
                    className="text-button danger"
                    title="Delete folder"
                    style={{ color: '#bf4c43' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setPendingDeleteFolder(folder);
                    }}
                  >
                    ×
                  </button>
                )}
              </div>
              <button
                className="folder-inner"
                style={{ background: 'transparent', border: 0, textAlign: 'left', padding: 0, margin: 0, display: 'grid', gap: 7, width: '100%' }}
                onClick={() => go('folder', folder.folder_id, workspace)}
              >
                <span>▰</span>
                <b>{folder.folder_name}</b>
                <small>{folder.description || 'Folder'}</small>
              </button>
            </div>
          ))}</div>
        ) : <Empty title="This workspace is empty" body="Create a folder to begin organizing files." />}
      </section>
      )}
      {(!showSettings && !showMembers) && pendingDeleteFolder && (
        <ConfirmDialog
          title={`Delete "${pendingDeleteFolder.folder_name}"?`}
          body="This folder and its contents will be deleted. Are you sure you want to proceed?"
          confirmLabel="Delete folder"
          busy={busyFolderDelete}
          onCancel={() => setPendingDeleteFolder(null)}
          onConfirm={confirmDeleteFolder}
        />
      )}
    </div>
  );
}

function JoinRequestsPanel({ workspaceId, onMembersChanged }) {
  const { data, loading, error, reload } = useAsync(() => api.getJoinRequests(workspaceId), [workspaceId]);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);

  if (error) return <ErrorState message={error} retry={reload} />;
  if (loading || !data?.length) return null;

  const toggleAll = (e) => setSelected(e.target.checked ? new Set(data.map(req => req.request_id)) : new Set());
  const toggleOne = (id) => { const next = new Set(selected); next.has(id) ? next.delete(id) : next.add(id); setSelected(next); };

  const approveBulk = async () => { setBusy(true); try { await api.bulkApproveJoinRequests(workspaceId, Array.from(selected)); setSelected(new Set()); await reload(); onMembersChanged(); } catch (e) { alert(e.message); } finally { setBusy(false); } };
  const approve = async (id) => { setBusy(true); try { await api.approveJoinRequest(id); await reload(); onMembersChanged(); } catch (e) { alert(e.message); } finally { setBusy(false); } };
  const reject = async (id) => { setBusy(true); try { await api.rejectJoinRequest(id); await reload(); } catch (e) { alert(e.message); } finally { setBusy(false); } };

  return <section className="panel"><div className="panel-head"><div><h3>Join Requests</h3><p>Users waiting to access this workspace.</p></div>{selected.size > 0 && <button className="button primary" disabled={busy} onClick={approveBulk}>Approve Selected</button>}</div><div className="file-table"><div className="table-head" style={{ gridTemplateColumns: 'auto 1fr auto auto' }}><input type="checkbox" checked={selected.size === data.length} onChange={toggleAll} /><span>User ID</span><span>Status</span><span></span></div>{data.map(req => <div className="file-row" key={req.request_id} style={{ gridTemplateColumns: 'auto 1fr auto auto' }}><input type="checkbox" checked={selected.has(req.request_id)} onChange={() => toggleOne(req.request_id)} /><span>User #{req.user_id}</span><span>{req.status}</span><div className="member-actions"><button className="text-button" disabled={busy} onClick={() => approve(req.request_id)}>Approve</button><button className="text-button danger" disabled={busy} onClick={() => reject(req.request_id)}>Reject</button></div></div>)}</div></section>;
}

function WorkspaceSettings({ workspace, reload, goBack, onClose }) {
  const [form, setForm] = useState({ workspace_name: workspace.workspace_name, visibility: workspace.visibility });
  const [busy, setBusy] = useState(false); const [pendingDelete, setPendingDelete] = useState(false);
  const save = async (e) => { e.preventDefault(); setBusy(true); try { await api.updateWorkspace(workspace.workspace_id, form); await reload(); } catch (e) { alert(e.message); } finally { setBusy(false); } };
  const confirmDelete = async () => { setBusy(true); try { await api.deleteWorkspace(workspace.workspace_id); goBack(); } catch (e) { alert(e.message); setBusy(false); } };
  if (workspace.member_role !== 'OWNER' && workspace.member_role !== 'ADMIN') return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h3>Workspace Settings</h3>
          <p className="eyebrow" style={{ marginTop: 4 }}>ID: {workspace.workspace_id} <button className="text-button" type="button" onClick={() => { navigator.clipboard.writeText(workspace.workspace_id); alert('Copied ID'); }}>Copy</button></p>
        </div>
        {onClose && <button className="text-button" onClick={onClose}>Close</button>}
      </div>
      <form className="inline-form" onSubmit={save}>
        <Field label="Name" value={form.workspace_name} onChange={v => setForm({...form, workspace_name: v})} required />
        <label className="field">
          <span>Visibility</span>
          <select value={form.visibility} onChange={e => setForm({...form, visibility: e.target.value})}>
            <option value="PRIVATE">Private</option>
            <option value="SHARED">Shared</option>
            <option value="PUBLIC">Public</option>
          </select>
        </label>
        <button className="button primary" disabled={busy}>Save Changes</button>
      </form>
      {workspace.member_role === 'OWNER' && (
        <>
          <div className="divider" />
          <div>
            <button className="button danger text-button" onClick={() => setPendingDelete(true)}>
              Delete Workspace
            </button>
          </div>
          {pendingDelete && (
            <ConfirmDialog
              title="Delete Workspace?"
              body="This action is irreversible and permanently deletes the workspace, all its folders, files, and memberships."
              confirmLabel="Delete"
              busy={busy}
              onCancel={() => setPendingDelete(false)}
              onConfirm={confirmDelete}
            />
          )}
        </>
      )}
    </section>
  );
}

function memberDisplayName(profile, member, currentUser) {
  if (currentUser?.user_id === member.user_id) return currentUser.full_name || currentUser.username;
  if (profile?.full_name) return profile.full_name;
  if (profile?.username) return profile.username;
  return `User #${member.user_id}`;
}

function memberEmail(profile, member, currentUser) {
  if (currentUser?.user_id === member.user_id) return currentUser.email || '';
  return profile?.email || '';
}

function sameUserId(left, right) {
  const a = Number(left);
  const b = Number(right);
  return Number.isInteger(a) && a > 0 && a === b;
}

function isWorkspaceOwnerMember(member) {
  return member.role === 'OWNER';
}

function canManageMembers(role) { return role === 'OWNER' || role === 'ADMIN'; }
function canAddMembers(role) { return ['OWNER', 'ADMIN', 'EDITOR'].includes(role); }

function roleOptionsForChange(actorRole, member, currentUserId) {
  if (!canManageMembers(actorRole) || member.role === 'OWNER' || member.user_id === currentUserId) return [];
  if (actorRole === 'OWNER') return ['ADMIN', 'EDITOR', 'VIEWER'];
  if (member.role === 'ADMIN') return [];
  return ['EDITOR', 'VIEWER'];
}

function canRemoveMember(actorRole, member, currentUserId) {
  if (member.role === 'OWNER' || member.user_id === currentUserId) return false;
  if (actorRole === 'OWNER') return true;
  return actorRole === 'ADMIN' && member.role !== 'ADMIN';
}

function ConfirmDialog({ title, body, confirmLabel, onConfirm, onCancel, busy }) {
  return (
    <div className="modal-backdrop">
      <form className="modal" onSubmit={(event) => { event.preventDefault(); onConfirm(); }}>
        <button type="button" className="modal-close" onClick={onCancel}>×</button>
        <p className="eyebrow">CONFIRM</p>
        <h3>{title}</h3>
        <p className="muted">{body}</p>
        <div className="confirm-actions">
          <button type="button" className="button secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="button primary" disabled={busy}>{busy ? 'Please wait…' : confirmLabel}</button>
        </div>
      </form>
    </div>
  );
}

function WorkspaceMembers({ workspaceId, workspace, currentUser, membersState, onWorkspaceChanged, onClose }) {
  const actorRole = workspace.member_role;
  const members = membersState.data || [];
  const memberIds = members.map((member) => member.user_id);
  const [profiles, setProfiles] = useState({});
  const [notice, setNotice] = useState({ text: '', tone: '' });
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState(null);
  const [selected, setSelected] = useState(null);
  const [inviteRole, setInviteRole] = useState('VIEWER');
  const [inviting, setInviting] = useState(false);
  const [pendingRemove, setPendingRemove] = useState(null);
  const [transferId, setTransferId] = useState('');
  const [pendingTransfer, setPendingTransfer] = useState(null);
  const [busy, setBusy] = useState(false);
  const searchTimer = useRef(null);

  useEffect(() => {
    let cancelled = false;
    if (!members.length) { setProfiles({}); return undefined; }
    Promise.all(members.map(async (member) => {
      if (currentUser?.user_id === member.user_id) return [member.user_id, currentUser];
      try { return [member.user_id, await api.user(member.user_id)]; }
      catch { return [member.user_id, null]; }
    })).then((entries) => { if (!cancelled) setProfiles(Object.fromEntries(entries)); });
    return () => { cancelled = true; };
  }, [membersState.data, currentUser]);

  useEffect(() => () => clearTimeout(searchTimer.current), []);

  const showNotice = (text, tone = '') => setNotice({ text, tone });

  const runSearch = (value) => {
    setQuery(value);
    setResults(null);
    clearTimeout(searchTimer.current);
    const term = value.trim();
    if (!term) { setSearching(false); return; }
    setSearching(true);
    searchTimer.current = setTimeout(async () => {
      try {
        const users = await api.searchUsers(term);
        setResults(users.filter((user) => !memberIds.includes(user.user_id)));
      } catch (err) {
        setResults([]);
        showNotice(err.message);
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  const invite = async (event) => {
    event.preventDefault();
    if (!selected) { showNotice('Select a user to add.'); return; }
    setInviting(true);
    showNotice('');
    try {
      await api.addWorkspaceMember(workspaceId, { user_id: selected.user_id, role: inviteRole });
      setSelected(null); setQuery(''); setResults(null); setInviteRole('VIEWER');
      showNotice(`${selected.full_name || selected.username} was added as ${inviteRole}.`, 'success');
      await membersState.reload();
    } catch (err) {
      showNotice(err.message);
    } finally {
      setInviting(false);
    }
  };

  const changeRole = async (member, role) => {
    if (role === member.role) return;
    showNotice('');
    try {
      await api.updateWorkspaceMember(workspaceId, member.user_id, { role });
      showNotice('Member role updated.', 'success');
      await membersState.reload();
    } catch (err) {
      showNotice(err.message);
    }
  };

  const confirmRemove = async () => {
    if (!pendingRemove) return;
    setBusy(true);
    try {
      await api.removeWorkspaceMember(workspaceId, pendingRemove.user_id);
      setPendingRemove(null);
      showNotice('Member removed from this workspace.', 'success');
      await membersState.reload();
    } catch (err) {
      showNotice(err.message);
    } finally {
      setBusy(false);
    }
  };

  const confirmTransfer = async () => {
    if (!pendingTransfer) return;
    setBusy(true);
    try {
      await api.transferWorkspaceOwnership(workspaceId, { user_id: pendingTransfer.user_id });
      setPendingTransfer(null);
      setTransferId('');
      showNotice('Ownership transferred. You are now an ADMIN.', 'success');
      await Promise.all([onWorkspaceChanged(), membersState.reload()]);
    } catch (err) {
      showNotice(err.message);
    } finally {
      setBusy(false);
    }
  };

  const transferCandidates = members.filter((member) => !isWorkspaceOwnerMember(member));
  const selectedTransfer = transferCandidates.find((member) => sameUserId(member.user_id, transferId));

  return (
    <section className="panel members-panel">
      <div className="panel-head">
        <div>
          <h3>Members</h3>
          <p className="eyebrow" style={{ marginTop: 4 }}>Workspace ID: {workspaceId} <button className="text-button" type="button" onClick={() => { navigator.clipboard.writeText(workspaceId); showNotice('Copied ID', 'success'); }}>Copy</button></p>
          <p>People who can access this workspace, and the role assigned to each of them.</p>
        </div>
        {onClose && <button className="text-button" onClick={onClose}>Close</button>}
      </div>
      {notice.text && <div className={`notice ${notice.tone}`}>{notice.text}</div>}
      {canAddMembers(actorRole) && (
        <form className="inline-form" onSubmit={invite}>
          <Field label="Search AETHERA users" value={query} onChange={runSearch} placeholder="Search by name or username" />
          <label className="field">
            <span>Role</span>
            <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}>
              <option value="EDITOR">EDITOR</option>
              <option value="VIEWER">VIEWER</option>
            </select>
          </label>
          <div className="invite-search">
            {selected && (
              <div className="selected-user">
                <span><b>{selected.full_name}</b> @{selected.username}</span>
                <button type="button" className="text-button" onClick={() => setSelected(null)}>Clear</button>
              </div>
            )}
            {searching && <div className="loading">Searching users…</div>}
            {!searching && query.trim() && results?.length === 0 && <p className="muted">No users match that search, or they are already members.</p>}
            {!searching && results?.length > 0 && (
              <div className="search-results">
                {results.map((user) => (
                  <button type="button" className={`search-result ${selected?.user_id === user.user_id ? 'selected' : ''}`} key={user.user_id} onClick={() => setSelected(user)}>
                    <span><b>{user.full_name}</b><small className="muted"> @{user.username}</small></span>
                    <span className="muted">{user.account_type}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button className="button primary" disabled={inviting || !selected}>{inviting ? 'Adding…' : 'Add member'}</button>
        </form>
      )}
      {actorRole === 'OWNER' && (
        <form className="compact-form" onSubmit={(event) => { event.preventDefault(); if (selectedTransfer) setPendingTransfer(selectedTransfer); }}>
          <select value={transferId} onChange={(event) => setTransferId(event.target.value)} required disabled={!transferCandidates.length}>
            <option value="">{transferCandidates.length ? 'Transfer ownership to…' : 'No eligible members'}</option>
            {transferCandidates.map((member) => (
              <option value={member.user_id} key={member.user_id}>
                {memberDisplayName(profiles[member.user_id], member, currentUser)} ({member.role})
              </option>
            ))}
          </select>
          <button className="button secondary" disabled={!transferCandidates.length}>Transfer ownership</button>
        </form>
      )}
      {actorRole === 'OWNER' && !transferCandidates.length && (
        <p className="muted">Ownership can only be transferred to another existing member. Add a member first.</p>
      )}
      {membersState.error ? <ErrorState message={membersState.error} retry={membersState.reload} /> : membersState.loading ? <Loading /> : members.length ? (
        <div className="file-table member-table">
          <div className="table-head"><span>Member</span><span>Email</span><span>Role</span><span></span></div>
          {members.map((member) => {
            const profile = profiles[member.user_id];
            const options = roleOptionsForChange(actorRole, member, currentUser?.user_id);
            const removable = canRemoveMember(actorRole, member, currentUser?.user_id);
            return (
              <div className="file-row" key={member.member_id}>
                <span><b>◎</b> {memberDisplayName(profile, member, currentUser)}{currentUser?.user_id === member.user_id ? ' (you)' : ''}{profile?.username ? <small className="muted"> @{profile.username}</small> : null}</span>
                <span>{memberEmail(profile, member, currentUser) || '—'}</span>
                <span>{member.role}</span>
                <div className="member-actions">
                  {options.length > 0 && (
                    <select aria-label={`Change role for ${memberDisplayName(profile, member, currentUser)}`} value={member.role} onChange={(event) => changeRole(member, event.target.value)}>
                      {options.map((role) => <option value={role} key={role}>{role}</option>)}
                    </select>
                  )}
                  {removable && <button type="button" className="text-button danger" onClick={() => setPendingRemove(member)}>Remove</button>}
                </div>
              </div>
            );
          })}
        </div>
      ) : <Empty title="No members yet" body="This workspace has no members in the backend." />}
      {pendingRemove && (
        <ConfirmDialog
          title={`Remove ${memberDisplayName(profiles[pendingRemove.user_id], pendingRemove, currentUser)}?`}
          body="They will lose access to this workspace. You can add them again later."
          confirmLabel="Remove member"
          busy={busy}
          onCancel={() => setPendingRemove(null)}
          onConfirm={confirmRemove}
        />
      )}
      {pendingTransfer && (
        <ConfirmDialog
          title="Transfer ownership?"
          body="You will become an ADMIN and the selected member will become the OWNER."
          confirmLabel="Transfer ownership"
          busy={busy}
          onCancel={() => setPendingTransfer(null)}
          onConfirm={confirmTransfer}
        />
      )}
    </section>
  );
}

function FolderBrowser({ folderId, workspace, back, go, currentUser }) {
  const { data: folder, loading: folderLoading, error: folderError } = useAsync(() => api.folder(folderId), [folderId]);
  const foldersState = useAsync(() => api.folders(workspace.workspace_id), [workspace.workspace_id]);
  const [showTrash, setShowTrash] = useState(false);
  const filesState = useAsync(() => api.files(folderId, { includeDeleted: showTrash }), [folderId, showTrash]);
  const [selected, setSelected] = useState(null);
  const [details, setDetails] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [pendingFolderDelete, setPendingFolderDelete] = useState(false);
  const [busyFolderDelete, setBusyFolderDelete] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [notice, setNotice] = useState({ text: '', tone: '' });
  const fileInputRef = useRef(null);

  const visibleFiles = (filesState.data || []).filter((file) => (showTrash ? file.is_deleted : !file.is_deleted));
  const canWrite = ['OWNER', 'ADMIN', 'EDITOR'].includes(workspace.member_role);
  const canManageFiles = ['OWNER', 'ADMIN'].includes(workspace.member_role);
  const canDeleteCurrentFolder = ['OWNER', 'ADMIN'].includes(workspace.member_role) || (workspace.member_role === 'EDITOR' && sameUserId(folder?.created_by, currentUser?.user_id));
  const childFolders = (foldersState.data || []).filter((item) => item.parent_folder_id === folderId);

  const upload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setNotice({ text: '', tone: '' });
    try {
      await api.uploadFile(folderId, file);
      setNotice({ text: `"${file.name}" uploaded successfully.`, tone: 'success' });
      await filesState.reload();
    } catch (error) {
      setNotice({ text: error.message || 'Upload failed.', tone: '' });
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  const download = async (file) => {
    setBusyId(file.file_id);
    setNotice({ text: '', tone: '' });
    try {
      const result = await api.downloadFile(file.file_id);
      if (!result?.download_url) throw new Error('Download link was not available.');
      window.open(result.download_url, '_blank', 'noopener,noreferrer');
    } catch (error) {
      setNotice({ text: error.message || 'Download failed.', tone: '' });
    } finally {
      setBusyId(null);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setBusyId(pendingDelete.file_id);
    try {
      await api.deleteFile(pendingDelete.file_id);
      setNotice({ text: `"${pendingDelete.file_name}" moved to trash.`, tone: 'success' });
      setPendingDelete(null);
      await filesState.reload();
    } catch (error) {
      setNotice({ text: error.message || 'Could not delete file.', tone: '' });
      setPendingDelete(null);
    } finally {
      setBusyId(null);
    }
  };

  const restore = async (file) => {
    setBusyId(file.file_id);
    setNotice({ text: '', tone: '' });
    try {
      await api.restoreFile(file.file_id);
      setNotice({ text: `"${file.file_name}" restored.`, tone: 'success' });
      await filesState.reload();
    } catch (error) {
      setNotice({ text: error.message || 'Could not restore file.', tone: '' });
    } finally {
      setBusyId(null);
    }
  };

  const goBack = () => {
    if (folder?.parent_folder_id) go('folder', folder.parent_folder_id, workspace);
    else back();
  };

  if (folderError) return <ErrorState message={folderError} />;
  if (folderLoading) return <Loading />;

  return (
    <div className="page-content">
      <button className="back" onClick={goBack}>← {folder?.parent_folder_id ? 'Parent folder' : workspace.workspace_name}</button>
      <section className="browser-title">
        <div>
          <p className="eyebrow">FOLDER</p>
          <h1>▰ {folder?.folder_name || 'Folder'}</h1>
          <p>{folder?.description || 'Files stored in this folder.'}</p>
        </div>
        <div className="page-actions">
          <button type="button" className="button secondary" onClick={() => { setShowTrash(false); setNotice({ text: '', tone: '' }); }} disabled={!showTrash}>Files</button>
          {canManageFiles && <button type="button" className="button secondary" onClick={() => { setShowTrash(true); setNotice({ text: '', tone: '' }); }} disabled={showTrash}>Trash</button>}
          {!showTrash && canWrite && (
            <>
              <input ref={fileInputRef} type="file" hidden onChange={upload} />
              <button type="button" className="button secondary" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
                {uploading ? 'Uploading…' : 'Upload file'}
              </button>
            </>
          )}
          {canDeleteCurrentFolder && (
            <button type="button" className="button secondary danger text-button" onClick={() => setPendingFolderDelete(true)}>
              Delete folder
            </button>
          )}
        </div>
      </section>
      {notice.text && <div className={`notice${notice.tone === 'success' ? ' success' : ''}`}>{notice.text}</div>}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h3>{showTrash ? 'Trash' : 'Files'}</h3>
            <p>{showTrash ? 'Soft-deleted files in this folder.' : 'Files in the currently selected folder.'}</p>
          </div>
        </div>
        {filesState.error ? <ErrorState message={filesState.error} retry={filesState.reload} /> : filesState.loading ? <Loading /> : visibleFiles.length ? (
          <div className="file-table">
            <div className="table-head"><span>Name</span><span>Type</span><span>Size</span><span>Updated</span><span></span></div>
            {visibleFiles.map((file) => (
              <div className="file-row" key={file.file_id}>
                <span><b>▧</b> {file.file_name || file.original_file_name || file.name || `File #${file.file_id}`}{file.is_deleted ? <small className="muted"> · deleted</small> : null}</span>
                <span>{file.mime_type || file.file_extension || '—'}</span>
                <span>{formatBytes(file.file_size)}</span>
                <span>{formatDate(file.updated_at)}</span>
                <div className="member-actions">
                  <button type="button" className="text-button" onClick={async () => {
                    setDetails(file);
                    if (file.is_deleted) return;
                    try { setDetails(await api.file(file.file_id)); } catch (_) { /* keep listed metadata */ }
                  }}>Details</button>
                  {!file.is_deleted && (
                    <>
                      <button type="button" className="text-button" disabled={busyId === file.file_id} onClick={() => download(file)}>
                        {busyId === file.file_id ? 'Opening…' : 'Download'}
                      </button>
                       {canManageFiles && <button type="button" className="text-button" onClick={() => setSelected(file)}>Share</button>}
                       {canManageFiles && <button type="button" className="text-button danger" disabled={busyId === file.file_id} onClick={() => setPendingDelete(file)}>Delete</button>}
                    </>
                  )}
                   {file.is_deleted && canManageFiles && (
                    <button type="button" className="text-button" disabled={busyId === file.file_id} onClick={() => restore(file)}>
                      {busyId === file.file_id ? 'Restoring…' : 'Restore'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title={showTrash ? 'Trash is empty' : 'No files in this folder'}
            body={showTrash ? 'Deleted files will appear here until they are restored.' : 'Upload a file to store it in this folder.'}
          />
        )}
      </section>
      {selected && <ShareDialog file={selected} close={() => setSelected(null)} onCreated={() => go('shared')} />}
      {details && (
        <div className="modal-backdrop">
          <div className="modal">
            <button type="button" className="modal-close" onClick={() => setDetails(null)}>×</button>
            <p className="eyebrow">FILE DETAILS</p>
            <h3>{details.file_name}</h3>
            <p className="muted">Original name: {details.original_file_name}</p>
            <p className="muted">Type: {details.mime_type || details.file_extension || '—'}</p>
            <p className="muted">Size: {formatBytes(details.file_size)}</p>
            <p className="muted">Created: {formatDate(details.created_at)}</p>
            <p className="muted">Updated: {formatDate(details.updated_at)}</p>
            <p className="muted">Status: {details.is_deleted ? 'In trash' : details.is_archived ? 'Archived' : 'Active'}{details.is_favorite ? ' · Favorite' : ''}</p>
            <button type="button" className="button secondary file-details-close" onClick={() => setDetails(null)}>Close</button>
          </div>
        </div>
      )}
      {pendingDelete && (
        <ConfirmDialog
          title={`Delete ${pendingDelete.file_name}?`}
          body="This moves the file to trash. You can restore it later from the Trash view."
          confirmLabel="Delete"
          busy={busyId === pendingDelete.file_id}
          onCancel={() => setPendingDelete(null)}
          onConfirm={confirmDelete}
        />
      )}
      {pendingFolderDelete && (
        <ConfirmDialog
          title={`Delete "${folder?.folder_name}"?`}
          body="This folder and all its contents will be deleted. This action cannot be undone."
          confirmLabel="Delete folder"
          busy={busyFolderDelete}
          onCancel={() => setPendingFolderDelete(false)}
          onConfirm={async () => {
            setBusyFolderDelete(true);
            try {
              await api.deleteFolder(folderId);
              go('workspace', workspace.workspace_id);
            } catch (err) {
              alert(err.message);
              setBusyFolderDelete(false);
            }
          }}
        />
      )}
    </div>
  );
}

function ShareDialog({ file, close, onCreated }) { const [form, setForm] = useState({ share_type: 'LINK', permission: 'VIEW', shared_with: '', expires_at: '' }); const [error, setError] = useState(''); const submit = async (e) => { e.preventDefault(); try { const payload = { file_id: file.file_id, share_type: form.share_type, permission: form.permission }; if (form.share_type === 'PRIVATE' && form.shared_with) payload.shared_with = Number(form.shared_with); if (form.expires_at) payload.expires_at = new Date(form.expires_at).toISOString(); await api.createShare(payload); onCreated(); } catch (err) { setError(err.message); } };
  return <div className="modal-backdrop"><form className="modal" onSubmit={submit}><button type="button" className="modal-close" onClick={close}>×</button><p className="eyebrow">SHARE FILE</p><h3>{file.file_name}</h3><label className="field"><span>Share type</span><select value={form.share_type} onChange={(e) => setForm({ ...form, share_type: e.target.value })}><option value="LINK">Link</option><option value="PUBLIC">Public</option><option value="PRIVATE">Private</option></select></label>{form.share_type === 'PRIVATE' && <Field label="Recipient user ID" type="number" value={form.shared_with} onChange={(shared_with) => setForm({ ...form, shared_with })} required />}<label className="field"><span>Permission</span><select value={form.permission} onChange={(e) => setForm({ ...form, permission: e.target.value })}><option value="VIEW">View</option><option value="EDIT">Edit</option></select></label><label className="field"><span>Expiration</span><select value={form.expires_at ? 'date' : 'never'} onChange={(e) => setForm({ ...form, expires_at: e.target.value === 'never' ? '' : form.expires_at || new Date(Date.now() + 86400000).toISOString().slice(0, 16) })}><option value="never">Never</option><option value="date">Expiration date/time</option></select></label>{form.expires_at && <Field label="Expires at" type="datetime-local" value={form.expires_at} onChange={(expires_at) => setForm({ ...form, expires_at })} required />}{error && <div className="notice">{error}</div>}<button className="button primary">Create share</button></form></div>; }

function SharedFiles() { const state = useAsync(api.shares, []); const revoke = async (id) => { if (!window.confirm('Revoke this share?')) return; try { await api.revokeShare(id); state.reload(); } catch (error) { alert(error.message); } };
  return <div className="page-content"><section className="panel"><div className="panel-head"><div><h3>Shared files</h3><p>Shares available to you or created by you.</p></div></div>{state.error ? <ErrorState message={state.error} retry={state.reload} /> : state.loading ? <Loading /> : state.data.length ? <div className="file-table"><div className="table-head"><span>File</span><span>Access</span><span>Shared with</span><span>Created</span><span></span></div>{state.data.map((share) => <div className="file-row" key={share.share_id}><span><b>▧</b> {share.file_name || `File #${share.file_id}`}</span><span>{share.share_type} · {share.permission}</span><span>{share.shared_with ? `User #${share.shared_with}` : 'Link / public'}</span><span>{formatDate(share.created_at)}</span><button className="text-button danger" onClick={() => revoke(share.share_id)}>Revoke</button></div>)}</div> : <Empty title="No shared files yet" body="When a file is shared through AETHERA, it will appear here." />}</section></div>; }

function Profile({ onUserChange }) { const state = useAsync(api.me, []); const [editing, setEditing] = useState(false); const [form, setForm] = useState(null); const [message, setMessage] = useState(''); useEffect(() => { if (state.data) setForm({ full_name: state.data.full_name, username: state.data.username, email: state.data.email, bio: state.data.bio || '' }); }, [state.data]); const save = async (e) => { e.preventDefault(); try { const user = await api.updateMe(form); onUserChange(user); setEditing(false); setMessage('Profile saved.'); state.reload(); } catch (err) { setMessage(err.message); } };
  if (state.error) return <ErrorState message={state.error} retry={state.reload} />; if (state.loading || !form) return <Loading />; const user = state.data;
  return <div className="page-content profile"><section className="profile-card"><div className="avatar">{user.full_name.slice(0, 1)}</div><div><h3>{user.full_name}</h3><p>@{user.username} · {user.account_type}</p><p className="muted">{user.email}</p></div><button className="button secondary" onClick={() => setEditing(!editing)}>{editing ? 'Cancel' : 'Edit profile'}</button></section>{message && <div className="notice success">{message}</div>}{editing && <form className="inline-form" onSubmit={save}><Field label="Full name" value={form.full_name} onChange={(full_name) => setForm({ ...form, full_name })} required /><Field label="Username" value={form.username} onChange={(username) => setForm({ ...form, username })} required /><Field label="Email" type="email" value={form.email} onChange={(email) => setForm({ ...form, email })} required /><label className="field"><span>Bio</span><textarea value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} /></label><button className="button primary">Save changes</button></form>}<section className="stat-grid"><Stat label="Storage used" value={formatBytes(user.storage_used)} /><Stat label="Storage limit" value={user.storage_limit ? formatBytes(user.storage_limit) : 'Unlimited'} /><Stat label="Email" value={user.email_verified ? 'Verified' : 'Unverified'} /></section></div>; }

function WorkspaceSearch({ go }) { const [query, setQuery] = useState(''); const [results, setResults] = useState([]); const [loading, setLoading] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState({ text: '', tone: '' });
  const search = async (e) => { e.preventDefault(); if (!query.trim()) return; setLoading(true); setError(''); setNotice({ text: '', tone: '' }); try { setResults(await api.searchWorkspaces(query)); } catch (err) { setError(err.message); } finally { setLoading(false); } };
  const requestJoin = async (id) => { setNotice({ text: '', tone: '' }); try { await api.requestJoinWorkspace(id); setNotice({ text: 'Join request sent successfully.', tone: 'success' }); } catch (err) { setNotice({ text: err.message, tone: '' }); } };
  return <div className="page-content"><section className="panel"><div className="panel-head"><div><h3>Search workspaces</h3><p>Find workspaces by ID or name. Public workspaces open read-only; private workspaces require approval.</p></div></div><form className="compact-form" onSubmit={search}><input placeholder="Workspace ID or name..." value={query} onChange={(e) => setQuery(e.target.value)} required /><button className="button primary" disabled={loading}>{loading ? 'Searching...' : 'Search'}</button></form>{notice.text && <div className={`notice ${notice.tone === 'success' ? 'success' : ''}`}>{notice.text}</div>}{error && <ErrorState message={error} />}{!loading && !error && results.length > 0 && <div className="file-table"><div className="table-head"><span>Name</span><span>ID</span><span>Owner</span><span>Visibility</span><span></span></div>{results.map((ws) => <div className="file-row" key={ws.workspace_id}><span><b>▦</b> {ws.workspace_name}</span><span>#{ws.workspace_id}</span><span>User #{ws.user_id}</span><span><span className={`badge ${ws.visibility.toLowerCase()}`}>{ws.visibility}</span></span><div className="member-actions">{ws.member_role || ws.visibility === 'PUBLIC' ? <button type="button" className="text-button" onClick={() => go('workspace', ws.workspace_id)}>Open</button> : <button type="button" className="text-button" onClick={() => requestJoin(ws.workspace_id)}>Request to Join</button>}</div></div>)}</div>}{!loading && !error && results.length === 0 && query && <Empty title="No results" body="Try a different search term." />}</section></div>; }

export default function App() { const [authenticated, setAuthenticated] = useState(Boolean(authStore.token)); const [page, setPage] = useState('dashboard'); const [params, setParams] = useState({}); const [user, setUser] = useState(null); const [oauthError, setOauthError] = useState(''); const googleHandoffStarted = useRef(false); const me = useAsync(() => authenticated ? api.me() : Promise.resolve(null), [authenticated]); useEffect(() => { if (me.data) setUser(me.data); }, [me.data]); useEffect(() => { const handler = () => setAuthenticated(false); window.addEventListener('aethera:unauthorized', handler); return () => window.removeEventListener('aethera:unauthorized', handler); }, []); useEffect(() => { const handoffCode = new URLSearchParams(window.location.search).get('oauth_code'); if (!handoffCode || googleHandoffStarted.current) return; googleHandoffStarted.current = true; api.exchangeGoogleOAuthCode(handoffCode).then((tokens) => { authStore.set(tokens); setAuthenticated(true); }).catch((error) => setOauthError(error.message || 'Google sign-in could not be completed.')).finally(() => window.history.replaceState({}, document.title, window.location.pathname)); }, []);
  const go = (next, id, workspace) => { setPage(next); setParams({ id, workspace }); }; const logout = async () => { try { await api.logout(); } catch (_) {} authStore.clear(); setAuthenticated(false); setPage('dashboard'); };
  if (!authenticated) return <AuthScreen onAuthenticated={() => setAuthenticated(true)} oauthError={oauthError} />;
  let content = page === 'dashboard' ? <Dashboard go={go} user={user} /> : page === 'workspaces' ? <Workspaces open={go} /> : page === 'search' ? <WorkspaceSearch go={go} /> : page === 'workspace' ? <WorkspaceDetail workspaceId={params.id} back={() => go('workspaces')} go={go} currentUser={user} /> : page === 'folder' ? <FolderBrowser folderId={params.id} workspace={params.workspace} back={() => go('workspace', params.workspace.workspace_id)} go={go} currentUser={user} /> : page === 'shared' ? <SharedFiles /> : <Profile onUserChange={setUser} />;
  return <AppShell page={page} setPage={setPage} onLogout={logout} user={user}>{content}</AppShell>;
}
