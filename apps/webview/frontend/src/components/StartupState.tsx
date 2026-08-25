import { AlertTriangle, LoaderCircle, PlugZap } from 'lucide-react'

export function StartupState({ loading, error }: { loading: boolean; error: Error | null }) {
  return (
    <section className="startup-state" aria-live="polite">
      <div className="startup-visual" aria-hidden="true">
        {loading ? <LoaderCircle className="spin" size={30} /> : <PlugZap size={30} />}
      </div>
      <div>
        <p className="eyebrow">Live data</p>
        <h1>{loading ? 'Connecting to chamber data' : 'Live data is unavailable'}</h1>
        <p>{error?.message ?? 'Waiting for the first complete chamber snapshot.'}</p>
      </div>
      {!loading && <AlertTriangle className="startup-warning" size={20} aria-hidden="true" />}
    </section>
  )
}