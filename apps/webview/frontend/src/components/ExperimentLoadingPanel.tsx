import { Database } from 'lucide-react'

export function ExperimentLoadingPanel({
  title = 'Loading experiment data',
  detail = 'Waiting for indexed and cloud-backed records.',
}: {
  title?: string
  detail?: string
}) {
  return (
    <section className="panel experiment-loading-panel" aria-live="polite" aria-busy="true">
      <div className="experiment-loading-heading">
        <Database size={20} aria-hidden="true" />
        <span><strong>{title}</strong><small>{detail}</small></span>
      </div>
      <div className="experiment-loading-marquee" aria-hidden="true"><span /></div>
    </section>
  )
}