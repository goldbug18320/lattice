import { useStore } from '../../store/index.js'

const STATUS_COLORS = {
  idle: '#6b7280',
  searching: '#f59e0b',
  tracking: '#f97316',
  engaging: '#ef4444',
  returning: '#10b981',
  patrolling: '#3b82f6',
  offline: '#374151',
}

const DRONE_ICONS = {
  recon: '👁',
  combat: '⚡',
  swarm_member: '◈',
}

export default function SwarmStatus() {
  const swarms = useStore(s => s.swarms)
  const drones = useStore(s => s.drones)
  const selectedSwarmId = useStore(s => s.selectedSwarmId)
  const selectSwarm = useStore(s => s.selectSwarm)

  const droneMap = Object.fromEntries(drones.map(d => [d.id, d]))

  const reconDrones = drones.filter(d => d.type === 'recon')
  const standaloneDrones = drones.filter(d => d.type === 'combat' && !d.swarm_id)

  return (
    <div className="panel swarm-panel">
      <div className="panel-header">
        <span className="panel-title">◈ SWARM & DRONE STATUS</span>
        <span className="panel-count">{drones.length} TOTAL</span>
      </div>

      {/* Swarms */}
      {swarms.map(swarm => {
        const swarmDrones = (swarm.drone_ids || []).map(id => droneMap[id]).filter(Boolean)
        const avgBattery = swarmDrones.length
          ? Math.round(swarmDrones.reduce((s, d) => s + (d.battery || 0), 0) / swarmDrones.length)
          : 0
        const statusColor = STATUS_COLORS[swarm.status] || '#6b7280'
        const isSelected = swarm.id === selectedSwarmId

        return (
          <div
            key={swarm.id}
            className={`swarm-card ${isSelected ? 'selected' : ''}`}
            onClick={() => selectSwarm(isSelected ? null : swarm.id)}
          >
            <div className="swarm-card-header">
              <div className="swarm-name">{swarm.name}</div>
              <div className="swarm-status" style={{ color: statusColor }}>
                ● {swarm.status.toUpperCase()}
              </div>
            </div>
            <div className="swarm-meta">
              <span>{swarmDrones.length} drones</span>
              <span className="battery-indicator">
                🔋 {avgBattery}%
                <div className="battery-bar">
                  <div className="battery-fill" style={{
                    width: `${avgBattery}%`,
                    background: avgBattery > 50 ? '#10b981' : avgBattery > 20 ? '#f59e0b' : '#ef4444'
                  }} />
                </div>
              </span>
            </div>
            {swarm.objective && (
              <div className="swarm-objective">📋 {swarm.objective}</div>
            )}
            {isSelected && (
              <div className="drone-list">
                {swarmDrones.map(d => (
                  <div key={d.id} className="drone-item">
                    <span className="drone-icon">{DRONE_ICONS[d.type] || '◈'}</span>
                    <span className="drone-name">{d.name}</span>
                    <span className="drone-status" style={{ color: STATUS_COLORS[d.status] || '#6b7280' }}>
                      {d.status}
                    </span>
                    <span className="drone-battery">🔋{Math.round(d.battery || 0)}%</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* Recon Drones */}
      {reconDrones.length > 0 && (
        <div className="section-group">
          <div className="section-label">RECONNAISSANCE</div>
          {reconDrones.map(d => (
            <div key={d.id} className="drone-item standalone">
              <span className="drone-icon">👁</span>
              <span className="drone-name">{d.name}</span>
              <span className="drone-status" style={{ color: STATUS_COLORS[d.status] || '#6b7280' }}>
                {d.status}
              </span>
              <span className="drone-battery">🔋{Math.round(d.battery || 0)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
