import { cn } from '@/lib/cn'

import { Button } from './Button'

interface SelectionQuickActionsProps {
  total: number
  selectedCount: number
  onSelectAll: () => void
  onSelectNone: () => void
  onInvert: () => void
  className?: string
}

/** "All / None / Invert" shortcut row for a checkbox-driven multi-select
 * list — the same three actions wherever the app lets you select multiple
 * items, instead of clicking every checkbox by hand. */
export function SelectionQuickActions({
  total,
  selectedCount,
  onSelectAll,
  onSelectNone,
  onInvert,
  className,
}: SelectionQuickActionsProps) {
  if (total === 0) return null
  return (
    <div className={cn('flex items-center gap-1', className)}>
      <Button variant="ghost" size="sm" onClick={onSelectAll} disabled={selectedCount === total}>
        All
      </Button>
      <Button variant="ghost" size="sm" onClick={onSelectNone} disabled={selectedCount === 0}>
        None
      </Button>
      <Button variant="ghost" size="sm" onClick={onInvert}>
        Invert
      </Button>
    </div>
  )
}
