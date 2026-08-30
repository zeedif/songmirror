import { cn } from '@/lib/cn'
import { serviceLogoId, tagText } from '@/lib/constants'
import type { LocalPlaylist } from '@/types'

import { Card } from '../ui/Card'
import { CoverArt } from '../ui/CoverArt'
import { ServiceLogo } from '../ui/ServiceLogo'

interface Props {
  playlist: LocalPlaylist
  onOpen: () => void
}

export function LocalPlaylistCard({ playlist, onOpen }: Props) {
  const boundProviders = Object.keys(playlist.links).filter((id) => serviceLogoId(id) !== null)

  return (
    <Card className="overflow-hidden p-0">
      <button type="button" onClick={onOpen} className="flex w-full flex-col gap-3 p-4 text-left hover:bg-surface-2 sm:p-5">
        <div className="flex items-center gap-3">
          <CoverArt image={playlist.image} className="size-11" />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[14px] font-bold text-text">{playlist.name}</h3>
            <p className="font-mono text-[11px] text-text-3">
              {playlist.tracks.length} track{playlist.tracks.length === 1 ? '' : 's'}
            </p>
          </div>
        </div>
        {playlist.description && (
          <p className="line-clamp-2 text-xs leading-relaxed text-text-3">{playlist.description}</p>
        )}
        <div className="flex items-center gap-1.5">
          {boundProviders.length > 0 ? (
            boundProviders.map((id) => {
              const logoId = serviceLogoId(id)
              return logoId ? (
                <ServiceLogo key={id} service={logoId} className={cn('size-3.5', tagText(id))} />
              ) : null
            })
          ) : (
            <span className="font-mono text-[10.5px] text-text-3">Not synced to any service yet</span>
          )}
        </div>
      </button>
    </Card>
  )
}
