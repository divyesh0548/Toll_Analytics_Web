import { cn } from '@/lib/utils'

/** Light plot-area wash so series colors read against the card. */
export function ChartInset({ className, children, ...props }) {
  return (
    <div
      className={cn('rounded-sm bg-muted/20 p-2 sm:p-3', className)}
      {...props}
    >
      {children}
    </div>
  )
}
