import { AlertTriangle, CircleCheck, ServerCog, ShieldCheck } from 'lucide-react'

import type { LiveViewState } from '../App'
import { StateLabel } from '../components/StatusGlyph'
import { StartupState } from '../components/StartupState'

export function SubsystemsPage({ live }: { live: LiveViewState }) {
  if (!live.snapshot) return <StartupState loading={live.isLoading} error={live.error} />
  const snapshot = live.snapshot
  const connected = snapshot.subsystems.filter((subsystem) => subsystem.connected).length
  const critical = snapshot.subsystems.filter((subsystem) => subsystem.critical).length
  const activeIssues = snapshot.subsystems.reduce((total, subsystem) => total + subsystem.issues.length, 0)

  return (
    <div className="page page-enter">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Illinois Plasma Institute Extreme Ultraviolet System</p>
          <h1>Subsystems</h1>
          <p>Status of the current chamber control system.</p>
        </div>
        <StateLabel state={snapshot.system.state} label={snapshot.system.label} />
      </section>

      <section className="subsystem-summary" aria-label="Subsystem summary">
        <span><ServerCog size={18} aria-hidden="true" /><strong>{connected} / {snapshot.subsystems.length}</strong><small>connected</small></span>
        <span><ShieldCheck size={18} aria-hidden="true" /><strong>{critical}</strong><small>required</small></span>
        <span><AlertTriangle size={18} aria-hidden="true" /><strong>{activeIssues}</strong><small>active issues</small></span>
      </section>

      <section className="panel subsystem-panel" aria-labelledby="subsystem-table-heading">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Current status</p>
            <h2 id="subsystem-table-heading">Known subsystems</h2>
          </div>
        </div>
        <div className="table-scroll" tabIndex={0} aria-label="Known subsystem statuses">
          <table className="data-table subsystem-table">
            <thead><tr><th>Subsystem</th><th>Connection</th><th>Primary status</th><th>Issues</th></tr></thead>
            <tbody>
              {snapshot.subsystems.map((subsystem) => (
                <tr key={subsystem.name}>
                  <td>
                    <span className="subsystem-name">
                      {subsystem.name}
                      {subsystem.critical && <small>Required</small>}
                    </span>
                  </td>
                  <td>
                    <span className={`connection-state ${subsystem.connected ? 'is-connected' : 'is-disconnected'}`}>
                      {subsystem.connected ? <CircleCheck size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}
                      {subsystem.connected ? 'Connected' : 'Disconnected'}
                    </span>
                  </td>
                  <td>{subsystem.primary_status}</td>
                  <td>
                    {subsystem.issues.length === 0 ? <span className="muted">None</span> : (
                      <span className="subsystem-issues">
                        {subsystem.issues.map((issue, index) => (
                          <span className={`issue issue-${issue.severity}`} key={`${issue.message}-${index}`}>{issue.message}</span>
                        ))}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}