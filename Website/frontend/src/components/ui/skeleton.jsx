import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader } from '@/components/ui/card'

export function Skeleton({ className, ...props }) {
  return (
    <div
      className={cn('animate-pulse rounded-sm bg-muted', className)}
      {...props}
    />
  )
}

/** KPI row + chart block placeholders for dashboard loads. */
export function DashboardSkeleton({ kpis = 5, className }) {
  return (
    <div className={cn('space-y-4', className)}>
      <div
        className={cn(
          'grid gap-3',
          kpis >= 5 ? 'sm:grid-cols-2 xl:grid-cols-5' : 'sm:grid-cols-2 xl:grid-cols-4',
        )}
      >
        {Array.from({ length: kpis }).map((_, index) => (
          <Card key={index} className="overflow-hidden shadow-sm">
            <div className="h-0.5 w-full bg-muted" />
            <CardContent className="space-y-2 p-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-7 w-28" />
              <Skeleton className="h-3 w-24" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader className="gap-2">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-64 max-w-full" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Card key={index}>
            <CardHeader className="gap-2">
              <Skeleton className="h-4 w-36" />
              <Skeleton className="h-3 w-28" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-40 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
