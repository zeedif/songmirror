import type { AccountState, EventKind, TransferStatus } from '../types'

interface StateStyle {
  label: string
  glyph: string
  badge: string
  text: string
}

/** connected→success · expired→warning · unconfigured→neutral · error→danger,
 * per the design spec's StatusPill map. Each pairs a mono glyph with the
 * word — color is never the only signal. */
export const ACCOUNT_STATE_STYLES: Record<AccountState, StateStyle> = {
  connected: { label: 'Connected', glyph: '✓', badge: 'bg-success-soft text-success', text: 'text-success' },
  expired: { label: 'Expired, reconnect', glyph: '~', badge: 'bg-warning-soft text-warning', text: 'text-warning' },
  error: { label: 'Error', glyph: '!', badge: 'bg-danger-soft text-danger', text: 'text-danger' },
  unconfigured: { label: 'Not configured', glyph: '·', badge: 'bg-neutral-soft text-neutral', text: 'text-neutral' },
}

export const TRANSFER_STATUS_STYLES: Record<TransferStatus, StateStyle> = {
  queued: { label: 'Queued', glyph: '·', badge: 'bg-neutral-soft text-neutral', text: 'text-neutral' },
  busy: { label: 'Waiting for the sync engine…', glyph: '~', badge: 'bg-warning-soft text-warning', text: 'text-warning' },
  running: { label: 'Running…', glyph: '…', badge: 'bg-accent-soft text-accent', text: 'text-accent' },
  paused: { label: 'Paused', glyph: '‖', badge: 'bg-neutral-soft text-neutral', text: 'text-neutral' },
  done: { label: 'Done', glyph: '✓', badge: 'bg-success-soft text-success', text: 'text-success' },
  stopped: { label: 'Stopped', glyph: '■', badge: 'bg-neutral-soft text-neutral', text: 'text-neutral' },
  error: { label: 'Error', glyph: '!', badge: 'bg-danger-soft text-danger', text: 'text-danger' },
}

interface ServiceStyle {
  label: string
  dot: string
  soft: string
  text: string
}

/** Service/source identity — dots + soft-tinted badges only, never buttons
 * (the app accent is teal). Engine events historically used a few shortened
 * tags, so normalize them before presenting or filtering them. */
const SERVICE_STYLES: Record<string, ServiceStyle> = {
  spotify: { label: 'Spotify', dot: 'bg-svc-spotify', soft: 'bg-svc-spotify-soft', text: 'text-svc-spotify' },
  tidal: { label: 'TIDAL', dot: 'bg-svc-tidal', soft: 'bg-svc-tidal-soft', text: 'text-svc-tidal' },
  qobuz: { label: 'Qobuz', dot: 'bg-svc-qobuz', soft: 'bg-svc-qobuz-soft', text: 'text-svc-qobuz' },
  deezer: { label: 'Deezer', dot: 'bg-svc-deezer', soft: 'bg-svc-deezer-soft', text: 'text-svc-deezer' },
  amazon: { label: 'Amazon Music', dot: 'bg-svc-amazon', soft: 'bg-svc-amazon-soft', text: 'text-svc-amazon' },
  apple: { label: 'Apple Music', dot: 'bg-svc-apple', soft: 'bg-svc-apple-soft', text: 'text-svc-apple' },
  ytmusic: { label: 'YouTube Music', dot: 'bg-svc-ytmusic', soft: 'bg-svc-ytmusic-soft', text: 'text-svc-ytmusic' },
  jellyfin: { label: 'Jellyfin', dot: 'bg-svc-jellyfin', soft: 'bg-svc-jellyfin-soft', text: 'text-svc-jellyfin' },
  sync: { label: 'Sync engine', dot: 'bg-accent', soft: 'bg-accent-soft', text: 'text-accent' },
  local: { label: 'Download mirror', dot: 'bg-info', soft: 'bg-info-soft', text: 'text-info' },
  transfer: { label: 'Playlist transfers', dot: 'bg-info', soft: 'bg-info-soft', text: 'text-info' },
  library: { label: 'Local library', dot: 'bg-neutral', soft: 'bg-neutral-soft', text: 'text-neutral' },
}
const SOURCE_ALIASES: Record<string, string> = {
  jelly: 'jellyfin',
  yt: 'ytmusic',
}
const DEFAULT_SERVICE_STYLE: ServiceStyle = {
  label: '',
  dot: 'bg-neutral',
  soft: 'bg-neutral-soft',
  text: 'text-neutral',
}

/** Stable source identity used by filters as well as display helpers. */
export function activitySourceId(tag: string): string {
  return SOURCE_ALIASES[tag] ?? tag
}

function humanizeTag(tag: string): string {
  return tag
    .replace(/[._-]+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toLocaleUpperCase())
}

export function tagLabel(tag: string): string {
  return SERVICE_STYLES[activitySourceId(tag)]?.label || humanizeTag(tag)
}
export function tagDot(tag: string): string {
  return (SERVICE_STYLES[activitySourceId(tag)] ?? DEFAULT_SERVICE_STYLE).dot
}
export function tagSoft(tag: string): string {
  return (SERVICE_STYLES[activitySourceId(tag)] ?? DEFAULT_SERVICE_STYLE).soft
}
export function tagText(tag: string): string {
  return (SERVICE_STYLES[activitySourceId(tag)] ?? DEFAULT_SERVICE_STYLE).text
}

/** Provider id -> ServiceLogo id (both the "yt" event tag and the "ytmusic"
 * account id resolve to the same YouTube Music mark). */
export function serviceLogoId(idOrTag: string): 'spotify' | 'tidal' | 'qobuz' | 'deezer' | 'amazon' | 'apple' | 'ytmusic' | 'jellyfin' | null {
  idOrTag = activitySourceId(idOrTag)
  if (idOrTag === 'spotify') return 'spotify'
  if (idOrTag === 'tidal') return 'tidal'
  if (idOrTag === 'qobuz') return 'qobuz'
  if (idOrTag === 'deezer') return 'deezer'
  if (idOrTag === 'amazon') return 'amazon'
  if (idOrTag === 'apple') return 'apple'
  if (idOrTag === 'ytmusic') return 'ytmusic'
  if (idOrTag === 'jellyfin') return 'jellyfin'
  return null
}

const SERVICE_HOME_URLS: Record<string, string> = {
  spotify: 'https://open.spotify.com/',
  tidal: 'https://listen.tidal.com/',
  qobuz: 'https://play.qobuz.com/',
  deezer: 'https://www.deezer.com/',
  amazon: 'https://music.amazon.com/',
  apple: 'https://music.apple.com/',
  ytmusic: 'https://music.youtube.com/',
}

export function serviceHomeUrl(idOrTag: string): string {
  return SERVICE_HOME_URLS[activitySourceId(idOrTag)] ?? ''
}

interface KindStyle {
  /** Plain-language name exposed alongside EventRow's visual action icon. */
  label: string
  tileBg: string
  tileText: string
  /** Message text color — miss rows dim relative to the rest. */
  text: string
  /** Extra classes for the whole row — used for kinds that deserve a
   * highlighted band (warnings, the pass-complete summary). */
  row?: string
}

export const KIND_STYLES: Record<EventKind, KindStyle> = {
  add: { label: 'Addition', tileBg: 'bg-success-soft', tileText: 'text-success', text: 'text-text' },
  remove: { label: 'Removal', tileBg: 'bg-danger-soft', tileText: 'text-danger', text: 'text-text' },
  hold: { label: 'Held', tileBg: 'bg-warning-soft', tileText: 'text-warning', text: 'text-text' },
  repair: { label: 'Identity repaired', tileBg: 'bg-info-soft', tileText: 'text-info', text: 'text-text' },
  miss: { label: 'Missing match', tileBg: 'bg-neutral-soft', tileText: 'text-neutral', text: 'text-text-2' },
  download: { label: 'Download', tileBg: 'bg-info-soft', tileText: 'text-info', text: 'text-text' },
  note: { label: 'Note', tileBg: 'bg-neutral-soft', tileText: 'text-neutral', text: 'text-text-2' },
  warn: {
    label: 'Warning',
    tileBg: 'bg-warning-soft',
    tileText: 'text-warning',
    text: 'font-semibold text-text',
    row: 'bg-warning-soft/40',
  },
  summary: {
    label: 'Pass complete',
    tileBg: 'bg-accent-soft',
    tileText: 'text-accent',
    text: 'font-semibold text-text',
    row: 'bg-surface-2',
  },
  section: { label: 'Section', tileBg: '', tileText: '', text: 'text-text-3' },
}

export const DOWNLOAD_FORMAT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Default (MP3)' },
  { value: 'mp3', label: 'MP3' },
  { value: 'flac', label: 'FLAC (lossless)' },
  { value: 'ogg', label: 'OGG Vorbis' },
  { value: 'opus', label: 'Opus (no re-encode from YouTube)' },
  { value: 'm4a', label: 'M4A / AAC' },
  { value: 'wav', label: 'WAV (uncompressed)' },
]
