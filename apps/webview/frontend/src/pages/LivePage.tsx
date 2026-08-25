import type { LiveViewState } from '../App'
import { BatchPanel } from '../components/BatchPanel'
import { ExperimentPanel } from '../components/ExperimentPanel'
import { MediaPanel } from '../components/MediaPanel'
import { StartupState } from '../components/StartupState'
import { StatusBand } from '../components/StatusBand'

export function LivePage({ live }: { live: LiveViewState }) {
  if (!live.snapshot) return <StartupState loading={live.isLoading} error={live.error} />
  return (
    <div className="page page-enter">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Illinois Plasma Institute Extreme Ultraviolet System</p>
          <h1>Live System Status</h1>
          <p>Current status of EUV tool</p>
        </div>
      </section>
      <StatusBand snapshot={live.snapshot} connectionState={live.connectionState} />
      <div className="live-grid">
        <div className="live-column">
          <ExperimentPanel snapshot={live.snapshot} />
          <BatchPanel snapshot={live.snapshot} />
        </div>
        <MediaPanel snapshot={live.snapshot} />
      </div>
    </div>
  )
}