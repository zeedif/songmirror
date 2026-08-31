import { useCallback, useEffect, useMemo, useState } from 'react'
import { LuTrash2 } from 'react-icons/lu'

import { api, errorMessage } from '@/api'
import { useProviderPlaylists } from '@/hooks/useProviderPlaylists'
import { serviceLogoId, tagText } from '@/lib/constants'
import { formatDuration } from '@/lib/format'
import type { Account, LocalPlaylistCompareResult, LocalPlaylistDiffTrack, LocalPlaylist, LocalPlaylistPushJob } from '@/types'

import { Button } from '../ui/Button'
import { ConfirmDialog } from '../ui/ConfirmDialog'
import { CoverArt } from '../ui/CoverArt'
import { Modal } from '../ui/Modal'
import { PlaylistPickerField } from '../ui/PlaylistPickerField'
import { SelectField } from '../ui/SelectField'
import { ServiceLogo } from '../ui/ServiceLogo'
import { TextField } from '../ui/TextField'
import { Toggle } from '../ui/Toggle'

/** One row in a diff list (`Push will add` / `Only on <service>`) — same
 * image + name/artist template as the provider PlaylistDetailModal's track
 * rows, so a track looks like the same track everywhere in the app. */
function DiffTrackRow({
  track,
  checkbox,
}: {
  track: LocalPlaylistDiffTrack
  checkbox?: { checked: boolean; onToggle: () => void }
}) {
  return (
    <li className="flex items-center gap-2.5 rounded-control px-2 py-1.5 hover:bg-surface-2">
      {checkbox && (
        <input
          type="checkbox"
          checked={checkbox.checked}
          onChange={checkbox.onToggle}
          aria-label={`Select ${track.name}`}
          className="size-4 shrink-0 accent-accent"
        />
      )}
      <CoverArt image={track.image} className="size-10" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold text-text">{track.name}</span>
        <span className="block truncate text-xs text-text-3">
          {[track.artist, track.album].filter(Boolean).join(' · ') || 'Unknown artist'}
        </span>
      </span>
      <span className="hidden shrink-0 font-mono text-[11px] text-text-3 sm:block">
        {formatDuration(track.duration_ms ? track.duration_ms / 1000 : null) ?? '—'}
      </span>
    </li>
  )
}

interface Props {
  playlistId: string | null
  accounts: Account[]
  onClose: () => void
  onChanged: () => void
}

const JOB_POLL_MS = 700

export function LocalPlaylistDetailModal({ playlistId, accounts, onClose, onChanged }: Props) {
  const [playlist, setPlaylist] = useState<LocalPlaylist | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [addName, setAddName] = useState('')
  const [addArtist, setAddArtist] = useState('')
  const [selectedTrackIds, setSelectedTrackIds] = useState<Set<string>>(new Set())

  const [provider, setProvider] = useState('')
  const [compareResult, setCompareResult] = useState<LocalPlaylistCompareResult | null>(null)
  const [comparing, setComparing] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [selectedPullIds, setSelectedPullIds] = useState<Set<string>>(new Set())
  const [allowRemovals, setAllowRemovals] = useState(false)
  const [maxRemovals, setMaxRemovals] = useState('50')
  const [pushConfirm, setPushConfirm] = useState<{ execute: boolean } | null>(null)
  const [pushing, setPushing] = useState(false)
  const [pushJob, setPushJob] = useState<LocalPlaylistPushJob | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const connected = useMemo(() => accounts.filter((a) => a.state === 'connected' && a.transferable), [accounts])
  const { entries } = useProviderPlaylists(provider ? [provider] : [])

  const load = useCallback(async () => {
    if (!playlistId) return
    setLoading(true)
    setError(null)
    try {
      setPlaylist(await api.getLocalPlaylist(playlistId))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [playlistId])

  useEffect(() => {
    setPlaylist(null)
    setError(null)
    setSelectedTrackIds(new Set())
    setProvider('')
    setCompareResult(null)
    setSelectedPullIds(new Set())
    setPushJob(null)
    setAllowRemovals(false)
    if (playlistId) void load()
  }, [playlistId, load])

  useEffect(() => {
    if (!pushJob || pushJob.status === 'done' || pushJob.status === 'error') return
    const timer = window.setTimeout(async () => {
      try {
        const updated = await api.getLocalPlaylistPushJob(pushJob.id)
        setPushJob(updated)
        if (updated.status === 'done') void load()
      } catch {
        // A transient poll failure just means we try again next tick.
      }
    }, JOB_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [pushJob, load])

  function toggleTrack(id: string) {
    setSelectedTrackIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function togglePull(id: string) {
    setSelectedPullIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleAddTrack(e: React.FormEvent) {
    e.preventDefault()
    if (!playlist || !addName.trim()) return
    try {
      setPlaylist(await api.addLocalPlaylistTrack(playlist.id, { name: addName.trim(), artist: addArtist.trim() }))
      setAddName('')
      setAddArtist('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function handleRemoveSelected() {
    if (!playlist || selectedTrackIds.size === 0) return
    try {
      setPlaylist(await api.removeLocalPlaylistTracks(playlist.id, [...selectedTrackIds]))
      setSelectedTrackIds(new Set())
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function handleBind(liveId: string) {
    if (!playlist || !provider) return
    try {
      setPlaylist(await api.bindLocalPlaylist(playlist.id, provider, liveId || null))
      setCompareResult(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function handleCompare() {
    if (!playlist || !provider) return
    setComparing(true)
    setError(null)
    try {
      setCompareResult(await api.compareLocalPlaylist(playlist.id, provider))
      setSelectedPullIds(new Set())
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setComparing(false)
    }
  }

  async function handlePull() {
    if (!playlist || !provider || selectedPullIds.size === 0) return
    setPulling(true)
    setError(null)
    try {
      setPlaylist(await api.pullLocalPlaylist(playlist.id, provider, [...selectedPullIds]))
      setCompareResult(null)
      setSelectedPullIds(new Set())
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPulling(false)
    }
  }

  async function handlePush(execute: boolean) {
    if (!playlist || !provider) return
    setPushing(true)
    setError(null)
    try {
      const res = await api.pushLocalPlaylist(playlist.id, provider, {
        execute,
        allow_removals: allowRemovals,
        max_removals: allowRemovals ? Number(maxRemovals) || 0 : 0,
      })
      setPushJob(await api.getLocalPlaylistPushJob(res.job_id))
      setPushConfirm(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPushing(false)
    }
  }

  async function handleDelete() {
    if (!playlist) return
    try {
      await api.deleteLocalPlaylist(playlist.id)
      onChanged()
      onClose()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const boundLiveId = playlist?.links[provider] ?? ''
  const providerName = connected.find((a) => a.id === provider)?.name ?? 'this service'

  return (
    <>
      <Modal
        open={playlistId !== null}
        onClose={onClose}
        title={playlist?.name ?? 'Playlist'}
        widthClassName="max-w-3xl"
        footer={
          <>
            <Button
              type="button"
              variant="danger-ghost"
              icon={<LuTrash2 className="size-4" aria-hidden="true" />}
              onClick={() => setDeleteConfirm(true)}
              disabled={!playlist}
            >
              Delete
            </Button>
            <Button type="button" variant="secondary" onClick={onClose}>
              Close
            </Button>
          </>
        }
      >
        {loading && !playlist ? (
          <p className="py-6 text-center text-sm text-text-3">Loading…</p>
        ) : playlist ? (
          <div className="flex flex-col gap-6 py-1">
            {error && <p className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

            <section className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <p className="text-[12.5px] font-semibold text-text-2">
                  Tracks ({playlist.tracks.length})
                </p>
                {selectedTrackIds.size > 0 && (
                  <Button variant="danger-ghost" size="sm" onClick={() => void handleRemoveSelected()}>
                    Remove {selectedTrackIds.size} selected
                  </Button>
                )}
              </div>
              {playlist.tracks.length === 0 ? (
                <p className="rounded-control border border-dashed border-border-strong px-3 py-4 text-center text-sm text-text-3">
                  No tracks yet — add one below, or clone/import into this playlist instead.
                </p>
              ) : (
                <ul className="thin-scrollbar flex max-h-64 flex-col gap-0.5 overflow-y-auto rounded-control border border-border p-1.5">
                  {playlist.tracks.map((track) => (
                    <li key={track.id} className="flex items-center gap-2.5 rounded-control px-2 py-1.5 hover:bg-surface-2">
                      <input
                        type="checkbox"
                        checked={selectedTrackIds.has(track.id)}
                        onChange={() => toggleTrack(track.id)}
                        className="size-4 shrink-0 accent-accent"
                      />
                      <CoverArt image={track.image} className="size-9" />
                      <span className="min-w-0 flex-1 truncate text-[13px] text-text">
                        {track.name}
                        {track.artist ? <span className="text-text-3"> — {track.artist}</span> : null}
                      </span>
                      <span className="flex shrink-0 items-center gap-1">
                        {Object.keys(track.links).map((id) => {
                          const logoId = serviceLogoId(id)
                          return logoId ? (
                            <ServiceLogo key={id} service={logoId} className={`size-3 ${tagText(id)}`} />
                          ) : null
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => void handleAddTrack(e)}>
                <div className="min-w-0 flex-1">
                  <TextField label="Add a track" placeholder="Title" value={addName} onChange={(e) => setAddName(e.target.value)} />
                </div>
                <div className="min-w-0 flex-1">
                  <TextField label="Artist" placeholder="Artist" value={addArtist} onChange={(e) => setAddArtist(e.target.value)} />
                </div>
                <Button type="submit" disabled={!addName.trim()}>Add</Button>
              </form>
            </section>

            <section className="flex flex-col gap-3 border-t border-border pt-5">
              <p className="text-[12.5px] font-semibold text-text-2">Sync with a service</p>
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
                      setCompareResult(null)
                    }}
                  />

                  {provider && (
                    <>
                      <PlaylistPickerField
                        label="Bound playlist"
                        help="Push writes here. Leave empty to create a new playlist on the next push."
                        placeholder="Create a new playlist on push"
                        playlists={entries[provider]?.playlists ?? []}
                        loading={entries[provider]?.loading}
                        value={boundLiveId}
                        onChange={(id) => void handleBind(id)}
                      />

                      <div className="flex items-center gap-2">
                        <Button variant="secondary" size="sm" loading={comparing} onClick={() => void handleCompare()} disabled={!boundLiveId}>
                          Compare
                        </Button>
                        {!boundLiveId && <p className="text-xs text-text-3">Bind a playlist to compare it.</p>}
                      </div>

                      {compareResult && (
                        <div className="flex flex-col gap-4">
                          <div className="flex flex-col gap-1.5">
                            <p className="font-mono text-[10.5px] font-semibold uppercase tracking-wide text-text-3">
                              Push will add ({compareResult.to_push_add.length})
                            </p>
                            {compareResult.to_push_add.length === 0 ? (
                              <p className="rounded-control border border-dashed border-border-strong px-3 py-3 text-center text-xs text-text-3">
                                Nothing to add — {providerName} already has everything from this playlist.
                              </p>
                            ) : (
                              <ul className="thin-scrollbar flex max-h-72 flex-col gap-0.5 overflow-y-auto rounded-card border border-border bg-inset p-1.5">
                                {compareResult.to_push_add.map((t) => (
                                  <DiffTrackRow key={t.id} track={t} />
                                ))}
                              </ul>
                            )}
                          </div>
                          <div className="flex flex-col gap-1.5">
                            <div className="flex items-center justify-between gap-2">
                              <p className="font-mono text-[10.5px] font-semibold uppercase tracking-wide text-text-3">
                                Only on {providerName} ({compareResult.provider_only.length})
                              </p>
                              {selectedPullIds.size > 0 && (
                                <Button variant="secondary" size="sm" loading={pulling} onClick={() => void handlePull()}>
                                  Pull {selectedPullIds.size} into this playlist
                                </Button>
                              )}
                            </div>
                            {compareResult.provider_only.length === 0 ? (
                              <p className="rounded-control border border-dashed border-border-strong px-3 py-3 text-center text-xs text-text-3">
                                Nothing extra on {providerName} — this playlist already has everything from there.
                              </p>
                            ) : (
                              <ul className="thin-scrollbar flex max-h-72 flex-col gap-0.5 overflow-y-auto rounded-card border border-border bg-inset p-1.5">
                                {compareResult.provider_only.map((t) => (
                                  <DiffTrackRow
                                    key={t.id}
                                    track={t}
                                    checkbox={{ checked: selectedPullIds.has(t.id), onToggle: () => togglePull(t.id) }}
                                  />
                                ))}
                              </ul>
                            )}
                          </div>
                        </div>
                      )}

                      <div className="flex flex-col gap-3 rounded-control border border-border bg-surface-2/45 p-3">
                        <Toggle
                          checked={allowRemovals}
                          onChange={setAllowRemovals}
                          label={`Delete extras on ${providerName}`}
                          description={`When pushing, also delete the tracks on ${providerName} that aren't in this local playlist (shown above as "Only on ${providerName}"). Off by default — a push only ever adds unless you turn this on.`}
                        />
                        {compareResult && compareResult.provider_only.length === 0 && (
                          <p className="text-xs text-text-3">
                            Nothing on {providerName} would be deleted right now — there's nothing extra there. Pulling a track above also takes it out of this list.
                          </p>
                        )}
                        {allowRemovals && (
                          <TextField
                            label="Removal cap"
                            help="A push stops and holds removals back if more than this many would be removed."
                            type="number"
                            min={0}
                            value={maxRemovals}
                            onChange={(e) => setMaxRemovals(e.target.value)}
                          />
                        )}
                        <div className="flex flex-wrap items-center gap-2">
                          <Button variant="secondary" onClick={() => void handlePush(false)} loading={pushing}>
                            Preview push
                          </Button>
                          <Button onClick={() => setPushConfirm({ execute: true })} disabled={pushing}>
                            Push now
                          </Button>
                        </div>
                      </div>

                      {pushJob && (
                        <div className="rounded-control border border-border p-3 text-sm">
                          <p className="font-semibold text-text">
                            {pushJob.status === 'running' || pushJob.status === 'queued'
                              ? `Pushing… ${pushJob.processed}/${pushJob.total || '?'}`
                              : pushJob.status === 'error'
                                ? `Push failed: ${pushJob.error}`
                                : `${pushJob.execute ? 'Pushed' : 'Preview'}: +${pushJob.added} -${pushJob.removed} (${pushJob.missing} missing, ${pushJob.held} held)`}
                          </p>
                          {pushJob.not_found.length > 0 && (
                            <ul className="mt-2 flex flex-col gap-0.5 text-xs text-text-3">
                              {pushJob.not_found.map((t, i) => (
                                <li key={i}>no match: {t.name} — {t.artist}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </>
              )}
            </section>
          </div>
        ) : null}
      </Modal>

      <ConfirmDialog
        open={pushConfirm !== null}
        title="Push now?"
        description={`This writes to "${provider}" for real — additions always apply, and removals apply too if "Mirror removals" is on.`}
        confirmLabel="Push"
        loading={pushing}
        onConfirm={() => void handlePush(true)}
        onCancel={() => setPushConfirm(null)}
      />
      <ConfirmDialog
        open={deleteConfirm}
        title="Delete this playlist?"
        description="This only removes it from SongMirror's local library — nothing is deleted from any connected service."
        confirmLabel="Delete"
        danger
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteConfirm(false)}
      />
    </>
  )
}
