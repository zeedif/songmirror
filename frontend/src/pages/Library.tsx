import { useState } from 'react'
import { LuTrash2 } from 'react-icons/lu'

import { api, errorMessage } from '@/api'
import { CloneFromProviderModal } from '@/components/library/CloneFromProviderModal'
import { CreateLocalPlaylistModal } from '@/components/library/CreateLocalPlaylistModal'
import { ImportBackupModal } from '@/components/library/ImportBackupModal'
import { LocalPlaylistCard } from '@/components/library/LocalPlaylistCard'
import { LocalPlaylistDetailModal } from '@/components/library/LocalPlaylistDetailModal'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { EmptyState } from '@/components/ui/EmptyState'
import { SelectionQuickActions } from '@/components/ui/SelectionQuickActions'
import { LoadingStatus, Skeleton } from '@/components/ui/Skeleton'
import { useAccounts } from '@/hooks/useAccounts'
import { useLocalPlaylists } from '@/hooks/useLocalPlaylists'

type ModalTarget = 'create' | 'clone' | 'import' | null

export default function Library() {
  const { accounts } = useAccounts()
  const { playlists, loading, error, refresh } = useLocalPlaylists()
  const [modal, setModal] = useState<ModalTarget>(null)
  const [openPlaylistId, setOpenPlaylistId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)

  function handleSaved() {
    setModal(null)
    void refresh()
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleBulkDelete() {
    if (selectedIds.size === 0) return
    setBulkDeleting(true)
    setBulkError(null)
    try {
      await Promise.all([...selectedIds].map((id) => api.deleteLocalPlaylist(id)))
      setSelectedIds(new Set())
      setBulkDeleteConfirm(false)
      void refresh()
    } catch (err) {
      setBulkError(errorMessage(err))
    } finally {
      setBulkDeleting(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-text sm:text-[22px]">Library</h1>
          <p className="mt-1 text-sm text-text-3">
            Playlists that live in SongMirror itself. Clone one from a service, build one by hand, or import a
            backup — then compare it against any connected service and push it back out.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => setModal('import')}>Import backup</Button>
          <Button variant="secondary" onClick={() => setModal('clone')}>Clone from a service</Button>
          <Button onClick={() => setModal('create')}>New playlist</Button>
        </div>
      </div>

      {error && (
        <p className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">Could not load your library: {error}</p>
      )}
      {bulkError && (
        <p className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">Could not delete: {bulkError}</p>
      )}

      {loading && !playlists ? (
        <LoadingStatus label="Loading your library…">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-28 w-full rounded-card" />
            ))}
          </div>
        </LoadingStatus>
      ) : playlists && playlists.length > 0 ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <SelectionQuickActions
              total={playlists.length}
              selectedCount={selectedIds.size}
              onSelectAll={() => setSelectedIds(new Set(playlists.map((p) => p.id)))}
              onSelectNone={() => setSelectedIds(new Set())}
              onInvert={() => setSelectedIds(new Set(playlists.filter((p) => !selectedIds.has(p.id)).map((p) => p.id)))}
            />
            {selectedIds.size > 0 && (
              <Button
                variant="danger-ghost"
                size="sm"
                icon={<LuTrash2 className="size-3.5" aria-hidden="true" />}
                onClick={() => setBulkDeleteConfirm(true)}
              >
                Delete {selectedIds.size} selected
              </Button>
            )}
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {playlists.map((playlist) => (
              <LocalPlaylistCard
                key={playlist.id}
                playlist={playlist}
                onOpen={() => setOpenPlaylistId(playlist.id)}
                selected={selectedIds.has(playlist.id)}
                onToggleSelect={() => toggleSelect(playlist.id)}
              />
            ))}
          </div>
        </>
      ) : (
        <EmptyState
          title="Your library is empty"
          description="Clone a playlist from a connected service, import a backup, or start one from scratch."
        />
      )}

      <CreateLocalPlaylistModal open={modal === 'create'} onClose={() => setModal(null)} onSaved={handleSaved} />
      <CloneFromProviderModal
        open={modal === 'clone'}
        onClose={() => setModal(null)}
        accounts={accounts ?? []}
        onSaved={handleSaved}
      />
      <ImportBackupModal open={modal === 'import'} onClose={() => setModal(null)} onSaved={handleSaved} />
      <LocalPlaylistDetailModal
        playlistId={openPlaylistId}
        accounts={accounts ?? []}
        onClose={() => setOpenPlaylistId(null)}
        onChanged={() => void refresh()}
      />
      <ConfirmDialog
        open={bulkDeleteConfirm}
        title={`Delete ${selectedIds.size} playlist${selectedIds.size === 1 ? '' : 's'}?`}
        description="This only removes them from SongMirror's local library — nothing is deleted from any connected service."
        confirmLabel="Delete"
        danger
        loading={bulkDeleting}
        onConfirm={() => void handleBulkDelete()}
        onCancel={() => setBulkDeleteConfirm(false)}
      />
    </div>
  )
}
