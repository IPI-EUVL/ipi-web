import { Activity, ChartNoAxesCombined, Database, ExternalLink, ScrollText, ServerCog } from 'lucide-react'
import { Link, Route, Switch, useLocation, useParams } from 'wouter'

import { useLiveSnapshot } from './api/live'
import type { LiveConnectionState } from './api/types'
import { LivePage } from './pages/LivePage'
import { SubsystemsPage } from './pages/SubsystemsPage'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { ExperimentDetailPage } from './pages/ExperimentDetailPage'
import { ExperimentAnalysisPage } from './pages/ExperimentAnalysisPage'
import { LogsPage } from './pages/LogsPage'

import ipiLogo from './assets/ipi.png'

const navigation = [
  { href: '/', label: 'Live', icon: Activity },
  { href: '/subsystems', label: 'Subsystems', icon: ServerCog },
  { href: '/experiments', label: 'Exposures', icon: Database },
  { href: '/logs', label: 'Logs', icon: ScrollText },
]

const connectionLabels: Record<LiveConnectionState, string> = {
  connecting: 'Connecting',
  live: 'Live',
  reconnecting: 'Reconnecting',
  offline: 'Offline',
}

function AppNavigation({ connectionState }: { connectionState: LiveConnectionState }) {
  const [location] = useLocation()
  const grafanaUrl = import.meta.env.VITE_GRAFANA_URL ?? 'http://localhost:3000/'

  return (
    <header className="app-header">
      <div className="brand-lockup">
        <span className="brand-mark" aria-hidden="true"><img src={ipiLogo} alt="IPI Logo" /></span>
        <span className="brand-copy">
          <strong>Illinois Plasma Institute Extreme Ultraviolet System</strong>
          <span>Live display</span>
        </span>
      </div>
      <nav className="primary-nav" aria-label="Primary navigation">
        {navigation.map(({ href, label, icon: Icon }) => {
          const active = href === '/' ? location === href : location.startsWith(href)
          return (
            <Link key={href} href={href} className="nav-link" aria-current={active ? 'page' : undefined}>
              <Icon size={16} aria-hidden="true" />
              <span>{label}</span>
            </Link>
          )
        })}
      </nav>
      <div className="header-actions">
        <span className={`connection-indicator connection-${connectionState}`}>
          <span className="connection-dot" aria-hidden="true" />
          {connectionLabels[connectionState]}
        </span>
        <a className="grafana-link" href={grafanaUrl} target="_blank" rel="noreferrer" aria-label="Open Grafana">
          <ChartNoAxesCombined size={16} aria-hidden="true" />
          <span>Grafana</span>
          <ExternalLink size={13} aria-hidden="true" />
        </a>
      </div>
    </header>
  )
}

function ExperimentDetailRoute() {
  const { runId } = useParams<{ runId: string }>()
  return <ExperimentDetailPage runId={runId ?? ''} />
}

export default function App() {
  const live = useLiveSnapshot()

  return (
    <div className="app-frame">
      <AppNavigation connectionState={live.connectionState} />
      <main className="app-main">
        <Switch>
          <Route path="/">
            <LivePage live={live} />
          </Route>
          <Route path="/subsystems">
            <SubsystemsPage live={live} />
          </Route>
          <Route path="/experiments">
            <ExperimentsPage />
          </Route>
          <Route path="/experiment-analysis">
            <ExperimentAnalysisPage />
          </Route>
          <Route path="/logs">
            <LogsPage />
          </Route>
          <Route path="/experiments/:runId" component={ExperimentDetailRoute} />
          <Route>
            <LivePage live={live} />
          </Route>
        </Switch>
      </main>
    </div>
  )
}

export type LiveViewState = ReturnType<typeof useLiveSnapshot>