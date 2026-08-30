import { useRef, useState } from 'react'

import { api, errorMessage } from '@/api'
import type { LocalPlaylistBackupPreview } from '@/types'

import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'

interface Props {
  open: boolean
  onClose: () => void
  onSaved: () => void
}

/** Imports one or more playlists from a SongMirror backup file, JSON or XML
 * (see the Playlists page's Export menu). Only SongMirror's own lossless
 * formats are accepted — reading one back is how a playlist moves between
 * accounts or SongMirror instances. Never binds a live resync target on
 * import, since the backup's playlist id may belong to a different account
 * than what's connected here. */
export function ImportBackupModal({ open, onClose, onSaved }: Props) {
  const [content, setContent] = useState<string | null>(null)
  const [preview, setPreview] = useState<LocalPlaylistBackupPreview | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [fileName, setFileName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleClose() {
    setContent(null)
    setPreview(null)
    setSelected(new Set())
    setFileName('')
    setError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
    onClose()
  }

  async function handleFile(file: File) {
    setError(null)
    setPreview(null)
    setFileName(file.name)
    try {
      const text = await file.text()
      const inspected = await api.inspectLocalPlaylistBackup(text)
      setContent(text)
      setPreview(inspected)
      setSelected(new Set(inspected.playlists.map((p) => p.id)))
    } catch (err) {
      setContent(null)
      setError(errorMessage(err))
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleImport() {
    if (!content || selected.size === 0) return
    setBusy(true)
    setError(null)
    try {
      await api.importLocalPlaylistBackup(content, [...selected])
      onSaved()
      handleClose()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Import a backup"
      description="Pick a songmirror-*.json or *.xml backup — from this instance, or one you downloaded from another account."
      footer={
        <>
          <Button type="button" variant="secondary" onClick={handleClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void handleImport()} loading={busy} disabled={selected.size === 0}>
            Import {selected.size > 0 ? `(${selected.size})` : ''}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 py-1">
        {error && <p className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

        <label className="flex h-11 cursor-pointer items-center justify-center gap-2 rounded-control border border-dashed border-border-strong bg-field text-sm text-text-2 hover:border-accent hover:text-text">
          {fileName || 'Choose a backup file…'}
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,application/xml,text/xml,.json,.xml"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void handleFile(file)
            }}
          />
        </label>

        {preview && (
          <div className="flex flex-col gap-2">
            <p className="text-[12.5px] font-semibold text-text-2">
              {preview.playlists.length} playlist{preview.playlists.length === 1 ? '' : 's'} in this backup
            </p>
            <div className="thin-scrollbar flex max-h-64 flex-col gap-1 overflow-y-auto rounded-control border border-border p-1.5">
              {preview.playlists.map((p) => (
                <label
                  key={p.id}
                  className="flex items-center gap-2.5 rounded-control px-2 py-1.5 text-sm hover:bg-surface-2"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    onChange={() => toggle(p.id)}
                    className="size-4 shrink-0 accent-accent"
                  />
                  <span className="min-w-0 flex-1 truncate text-text">{p.name || 'Untitled playlist'}</span>
                  <span className="shrink-0 font-mono text-[11px] text-text-3">{p.track_count} tracks</span>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
