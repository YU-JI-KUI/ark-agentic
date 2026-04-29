import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type StudioUserGrant } from '../api'
import { canManageUsers, type StudioRole, useAuth } from '../auth'
import { PlusIcon, RefreshIcon, SearchIcon } from '../components/StudioIcons'

type RoleFilter = StudioRole | 'all'
type FormMode = 'create' | 'edit'

const ROLE_OPTIONS: StudioRole[] = ['admin', 'editor', 'viewer']
const PAGE_SIZE = 50

function formatDate(value: string | null | undefined) {
  if (!value) return 'unknown'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'unknown'
  return parsed.toLocaleString()
}

function roleBadgeClass(role: StudioRole) {
  if (role === 'admin') return 'badge err'
  if (role === 'editor') return 'badge accent'
  return 'badge'
}

export default function UsersPage() {
  const { user } = useAuth()
  const canManage = canManageUsers(user?.role)
  const [users, setUsers] = useState<StudioUserGrant[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState<RoleFilter>('all')
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [adminCount, setAdminCount] = useState(0)
  const [mode, setMode] = useState<FormMode>('create')
  const [formOpen, setFormOpen] = useState(true)
  const [draftUserId, setDraftUserId] = useState('')
  const [draftRole, setDraftRole] = useState<StudioRole>('viewer')
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)

  const selectedUser = useMemo(
    () => users.find(item => item.user_id === selectedUserId) ?? null,
    [selectedUserId, users],
  )

  const isEditingLastAdmin = mode === 'edit' && selectedUser?.role === 'admin' && adminCount <= 1
  const pageStart = total === 0 ? 0 : offset + 1
  const pageEnd = Math.min(offset + users.length, total)
  const hasPreviousPage = offset > 0
  const hasNextPage = offset + users.length < total

  const loadUsers = useCallback(async (nextOffset = offset) => {
    setLoading(true)
    setError(null)
    try {
      const page = await api.listUsers({
        query,
        role: roleFilter,
        limit: PAGE_SIZE,
        offset: nextOffset,
      })
      setUsers(page.users)
      setTotal(page.total)
      setAdminCount(page.admin_count)
      setOffset(page.offset)
      setSelectedUserId(prev => {
        if (prev && page.users.some(item => item.user_id === prev)) return prev
        return page.users[0]?.user_id ?? null
      })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setLoading(false)
    }
  }, [offset, query, roleFilter])

  useEffect(() => {
    if (canManage) void loadUsers(offset)
    else setLoading(false)
  }, [canManage, loadUsers, offset])

  function handleQueryChange(value: string) {
    setQuery(value)
    setOffset(0)
  }

  function handleRoleFilterChange(value: RoleFilter) {
    setRoleFilter(value)
    setOffset(0)
  }

  useEffect(() => {
    if (mode !== 'edit' || !selectedUser) return
    setDraftUserId(selectedUser.user_id)
    setDraftRole(selectedUser.role)
  }, [mode, selectedUser])

  function startCreate() {
    setMode('create')
    setFormOpen(true)
    setSelectedUserId(null)
    setDraftUserId('')
    setDraftRole('viewer')
    setFeedback(null)
    setError(null)
  }

  function startEdit(item: StudioUserGrant) {
    setMode('edit')
    setFormOpen(true)
    setSelectedUserId(item.user_id)
    setDraftUserId(item.user_id)
    setDraftRole(item.role)
    setFeedback(null)
    setError(null)
  }

  function collapseForm() {
    setFormOpen(false)
    setMode('create')
    setSelectedUserId(null)
    setDraftUserId('')
    setDraftRole('viewer')
    setFeedback(null)
    setError(null)
  }

  function handleGrantRoleClick() {
    if (formOpen && mode === 'create') {
      collapseForm()
      return
    }
    startCreate()
  }

  async function handleSave() {
    const userId = draftUserId.trim()
    if (!userId) {
      setError('user_id is required')
      return
    }
    setSaving(true)
    setError(null)
    setFeedback(null)
    try {
      const saved = await api.saveUserGrant({ user_id: userId, role: draftRole })
      setFeedback(`Saved role for ${saved.user_id}`)
      await loadUsers(0)
      setMode('edit')
      setSelectedUserId(saved.user_id)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(item: StudioUserGrant) {
    if (item.role === 'admin' && adminCount <= 1) return
    const confirmed = window.confirm(`Delete role grant for ${item.user_id}?`)
    if (!confirmed) return
    setSaving(true)
    setError(null)
    setFeedback(null)
    try {
      await api.deleteUserGrant(item.user_id)
      setFeedback(`Deleted role grant for ${item.user_id}`)
      await loadUsers(Math.max(0, Math.min(offset, total - 1 - PAGE_SIZE)))
      setMode('create')
      setFormOpen(false)
      setSelectedUserId(null)
      setDraftUserId('')
      setDraftRole('viewer')
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setSaving(false)
    }
  }

  if (!canManage) {
    return (
      <section className="users-page">
        <div className="empty-surface">Access denied.</div>
      </section>
    )
  }

  return (
    <section className="users-page">
      <div className="users-page-header">
        <div>
          <h1>Users</h1>
          <p>Grant Studio roles by user ID.</p>
        </div>
        <div className="button-row">
          <button className="action-button" onClick={() => void loadUsers()} type="button">
            <RefreshIcon />
            Refresh
          </button>
          <button
            aria-controls="grant-user-role-panel"
            aria-expanded={formOpen && mode === 'create'}
            className={`action-button action-button-primary users-grant-toggle ${
              formOpen && mode === 'create' ? 'open' : ''
            }`}
            onClick={handleGrantRoleClick}
            title={formOpen && mode === 'create' ? 'Collapse grant form' : 'Grant role'}
            type="button"
          >
            <PlusIcon />
            Grant Role
          </button>
        </div>
      </div>

      <section className={`users-layout ${formOpen ? 'users-layout-form-open' : 'users-layout-form-collapsed'}`}>
        <div className="workspace-surface users-table-panel">
          <div className="filter-bar">
            <label className="search">
              <SearchIcon />
              <input
                aria-label="Search users"
                onChange={event => handleQueryChange(event.target.value)}
                placeholder="Search user ID"
                value={query}
              />
            </label>
            <select
              aria-label="Filter by role"
              className="field-input users-role-filter"
              onChange={event => handleRoleFilterChange(event.target.value as RoleFilter)}
              value={roleFilter}
            >
              <option value="all">All roles</option>
              {ROLE_OPTIONS.map(role => (
                <option key={role} value={role}>{role}</option>
              ))}
            </select>
          </div>

          {loading && <div className="empty-surface">Loading users...</div>}
          {error && <div className="feedback-banner feedback-banner-error">{error}</div>}
          {!loading && !error && users.length === 0 && (
            <div className="empty-surface">No user role grants found.</div>
          )}

          {!loading && users.length > 0 && (
            <div className="users-table-shell">
              <table className="users-table">
                <thead>
                  <tr>
                    <th>User ID</th>
                    <th>Role</th>
                    <th>Updated By</th>
                    <th>Updated At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(item => {
                    const isLastAdmin = item.role === 'admin' && adminCount <= 1
                    const isCurrentUser = item.user_id === user?.user_id
                    return (
                      <tr key={item.user_id} className={selectedUserId === item.user_id ? 'selected' : ''}>
                        <td><code>{item.user_id}</code></td>
                        <td><span className={roleBadgeClass(item.role)}>{item.role}</span></td>
                        <td>{item.updated_by || 'system'}</td>
                        <td>{formatDate(item.updated_at)}</td>
                        <td>
                          <div className="button-row">
                            {isCurrentUser ? (
                              <span className="badge">Current user</span>
                            ) : (
                              <>
                                <button className="action-button" onClick={() => startEdit(item)} type="button">
                                  Edit
                                </button>
                                <button
                                  className="action-button action-button-danger"
                                  disabled={isLastAdmin || saving}
                                  onClick={() => void handleDelete(item)}
                                  title={isLastAdmin ? 'At least one admin is required' : 'Delete role grant'}
                                  type="button"
                                >
                                  Delete
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="users-pagination">
            <span>{total === 0 ? '0 users' : `${pageStart}-${pageEnd} of ${total}`}</span>
            <div className="button-row">
              <button
                className="action-button"
                disabled={!hasPreviousPage || loading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                type="button"
              >
                Previous
              </button>
              <button
                className="action-button"
                disabled={!hasNextPage || loading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                type="button"
              >
                Next
              </button>
            </div>
          </div>
        </div>

        <aside
          aria-hidden={!formOpen}
          className={`workspace-surface users-form-panel ${formOpen ? 'open' : 'collapsed'}`}
          id="grant-user-role-panel"
        >
          {feedback && <div className="feedback-banner">{feedback}</div>}
          <div className="editor-sheet">
            <div className="surface-heading">
              <span>{mode === 'create' ? 'Grant User Role' : 'Edit User Role'}</span>
            </div>
            <label className="form-field">
              <span>User ID</span>
              <input
                disabled={mode === 'edit'}
                onChange={event => setDraftUserId(event.target.value)}
                placeholder="Enter user_id"
                value={draftUserId}
              />
            </label>
            <label className="form-field">
              <span>Role</span>
              <select
                disabled={isEditingLastAdmin}
                onChange={event => setDraftRole(event.target.value as StudioRole)}
                value={draftRole}
              >
                {ROLE_OPTIONS.map(role => (
                  <option key={role} value={role}>{role}</option>
                ))}
              </select>
            </label>
            {isEditingLastAdmin && (
              <div className="feedback-banner">At least one admin is required.</div>
            )}
            <div className="button-row">
              <button
                className="action-button action-button-primary"
                disabled={saving || !draftUserId.trim()}
                onClick={() => void handleSave()}
                type="button"
              >
                {saving ? 'Saving...' : 'Save Grant'}
              </button>
              <button className="action-button" onClick={collapseForm} type="button">
                Cancel
              </button>
            </div>
          </div>
        </aside>
      </section>
    </section>
  )
}
