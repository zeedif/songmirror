import { useEffect, useState } from 'react'

import { api, errorMessage } from '@/api'

import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { TextField } from '../ui/TextField'

interface Props {
  open: boolean
  onClose: () => void
  onSaved: () => void
}

/** A bare "New playlist" form — name + optional description. Tracks are
 * added afterward from the playlist's own detail view. */
export function CreateLocalPlaylistModal({ open, onClose, onSaved }: Props) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setName('')
    setDescription('')
    setError(null)
    setSaving(false)
  }, [open])

  async function handleSave() {
    if (!name.trim()) return
    setSaving(true)
    setError(null)
    try {
      await api.createLocalPlaylist(name.trim(), description.trim())
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New playlist"
      description="Starts empty — add tracks by hand, or clone/import one instead."
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="create-local-playlist-form" loading={saving} disabled={!name.trim()}>
            Create
          </Button>
        </>
      }
    >
      <form
        id="create-local-playlist-form"
        className="flex flex-col gap-4 py-1"
        onSubmit={(e) => {
          e.preventDefault()
          void handleSave()
        }}
      >
        {error && <p className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
      </form>
    </Modal>
  )
}
