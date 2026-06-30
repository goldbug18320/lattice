import { useEffect } from 'react'
import Map3D from './components/Map3D/index.jsx'
import AssetPalette from './components/AssetPalette/index.jsx'
import CommandPanel from './components/CommandPanel/index.jsx'
import SwarmStatus from './components/SwarmStatus/index.jsx'
import TargetList from './components/TargetList/index.jsx'
import ApprovalBar from './components/ApprovalBar/index.jsx'
import { connectWebSocket } from './services/websocket.js'
import { useStore } from './store/index.js'

export default function App() {
  const wsConnected = useStore(s => s.wsConnected)
  const wsStatus = useStore(s => s.wsStatus)
  const drones = useStore(s => s.drones)
  const targets = useStore(s => s.targets)
  const swarms = useStore(s => s.swarms)
  const pendingApprovals = useStore(s => s.pendingApprovals)
  const lastUpdate = useStore(s => s.lastUpdate)

  useEffect(() => {
    connectWebSocket()
  }, [])

  const statusColor = wsConnected ? '#10b981' : wsStatus === 'reconnecting' ? '#f59e0b' : '#ef4444'
  const activeTargets = targets.filter(t => !['destroyed', 'lost'].includes(t.status)).length
  const engagedTargets = targets.filter(t => t.status === 'engaged').length
  const trackedTargets = targets.filter(t => t.status === 'tracked').length

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="header-logo">
          <span className="logo-icon">⬡</span>
          <span className="logo-text">LATTICE</span>
          <span className="logo-sub">AI DRONE SWARM C2</span>
        </div>
        <div className="header-stats">
          <div className="stat">
            <span className="stat-label">DRONES</span>
            <span className="stat-value">{drones.length}</span>
          </div>
          <div className="stat">
            <span className="stat-label">SWARMS</span>
            <span className="stat-value">{swarms.length}</span>
          </div>
          <div className="stat threat">
            <span className="stat-label">TARGETS</span>
            <span className="stat-value">{activeTargets}</span>
          </div>
          <div className={`stat ${engagedTargets > 0 ? 'engaging' : ''}`}>
            <span className="stat-label">ENGAGED</span>
            <span className="stat-value">{engagedTargets}</span>
          </div>
          <div className={`stat ${trackedTargets > 0 ? 'tracking' : ''}`}>
            <span className="stat-label">TRACKED</span>
            <span className="stat-value">{trackedTargets}</span>
          </div>
          {pendingApprovals.length > 0 && (
            <div className="stat" style={{ color: '#ef4444', borderColor: '#7f1d1d' }}>
              <span className="stat-label">APPROVALS</span>
              <span className="stat-value" style={{ color: '#ef4444' }}>{pendingApprovals.length}</span>
            </div>
          )}
        </div>
        <div className="header-status">
          <span className="ws-indicator" style={{ color: statusColor }}>●</span>
          <span className="ws-label">{wsStatus.toUpperCase()}</span>
          {lastUpdate && (
            <span className="last-update">
              {new Date(lastUpdate).toLocaleTimeString()}
            </span>
          )}
        </div>
      </header>

      {/* Main Layout */}
      <main className="app-main">
        {/* Left Sidebar */}
        <aside className="sidebar sidebar-left">
          <SwarmStatus />
        </aside>

        {/* 3D Map (center) */}
        <section className="map-container" style={{ position: 'relative' }}>
          <Map3D />
          <AssetPalette />
          <div className="map-legend">
            <div className="legend-title">LEGEND</div>
            <div className="legend-item"><span style={{color:'#3b82f6'}}>●</span> Friendly Drone</div>
            <div className="legend-item"><span style={{color:'#3b82f6'}}>●</span> Returning</div>
            <div className="legend-item"><span style={{color:'#60a5fa'}}>●</span> Engaging</div>
            <div className="legend-item"><span style={{color:'#f59e0b'}}>●</span> Searching</div>
            <div className="legend-item"><span style={{color:'#f87171'}}>◆</span> Enemy Target</div>
          </div>
        </section>

        {/* Right Sidebar */}
        <aside className="sidebar sidebar-right">
          <TargetList />
        </aside>
      </main>

      {/* Approval Bar */}
      <ApprovalBar />

      {/* Bottom Panel */}
      <footer className="app-footer">
        <CommandPanel />
      </footer>
    </div>
  )
}
