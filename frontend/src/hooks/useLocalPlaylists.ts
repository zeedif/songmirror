import { api } from '@/api'
import { usePersistedResource } from '@/lib/persistedResource'
import type { LocalPlaylist } from '@/types'

function isLocalPlaylistArray(value: unknown): value is LocalPlaylist[] {
  return (
    Array.isArray(value) &&
    value.every((p) => p !== null && typeof p === 'object' && 'id' in p && typeof p.id === 'string')
  )
}

export function useLocalPlaylists() {
  const { data, loading, error, refresh } = usePersistedResource('local-playlists', api.getLocalPlaylists, isLocalPlaylistArray)
  return { playlists: data, loading, error, refresh }
}
