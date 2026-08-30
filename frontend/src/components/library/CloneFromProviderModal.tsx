import { useState } from 'react'

import { api, errorMessage } from '@/api'
import { useProviderPlaylists } from '@/hooks/useProviderPlaylists'
import { serviceLogoId, tagText } from '@/lib/constants'
import type { Account } from '@/types'

import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { PlaylistPickerField } from '../ui/PlaylistPickerField'
import { SelectField } from '../ui/SelectField'
import { ServiceLogo } from '../ui/ServiceLogo'

interface Props {
  open: boolean
  onClose: () => void
  accounts: Account[]
  onSaved: () => void
}

/** Clones a live provider playlist into a new local playlist — a fresh
 * snapshot, one time. Editing the local copy afterward never touches the
 * source playlist. */
export function CloneFromProviderModal({ open, onClose, accounts, onSaved }: Props) {
  const [provider, setProvider] = useState('')
  const [playlistId, setPlaylistId] = useState('')
  const [cloning, setCloning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const connected = accounts.filter((a) => a.state === 'connected' && a.transferable)
  const { entries } = useProviderPlaylists(provider ? [provider] : [])

  function handleClose() {
    setProvider('')
    setPlaylistId('')
    setError(null)
    onClose()
  }

  async function handleClone() {
    if (!provider || !playlistId) return
    setCloning(true)
    setError(null)
    try {
      await api.cloneLocalPlaylist(provider, playlistId)
      onSaved()
      handleClose()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setCloning(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Clone from a service"
      description="Takes a snapshot of a playlist you already have on a connected service, right now."
      footer={
        <>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={cloning}>
            Cancel
          </Button>
          <Button onClick={() => void handleClone()} loading={cloning} disabled={!provider || !playlistId}>
            Clone
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 py-1">
        {error && <p className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        {connected.length === 0 ? (
          <p className="text-sm text-text-3">Connect a service on the Accounts page first.</p>
        ) : (
          <>
            <SelectField
              label="Service"
              icon={
                serviceLogoId(provider) ? (
                  <ServiceLogo service={serviceLogoId(provider)!} className={`size-4 ${tagText(provider)}`} />
                ) : undefined
              }
              options={[{ value: '', label: 'Choose a service…' }, ...connected.map((a) => ({ value: a.id, label: a.name }))]}
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value)
                setPlaylistId('')
              }}
            />
            <PlaylistPickerField
              label="Playlist"
              playlists={entries[provider]?.playlists ?? []}
              loading={entries[provider]?.loading}
              value={playlistId}
              disabled={!provider}
              onChange={setPlaylistId}
            />
          </>
        )}
      </div>
    </Modal>
  )
}
