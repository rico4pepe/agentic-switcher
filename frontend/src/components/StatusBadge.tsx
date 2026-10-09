import type { Outcome } from '../outcome'

interface StatusBadgeProps {
  outcome: Outcome
}

export function StatusBadge({ outcome }: StatusBadgeProps) {
  return (
    <span
      className={`status-badge status-badge--${outcome.tone}`}
      data-outcome={outcome.kind}
    >
      {outcome.label}
    </span>
  )
}
