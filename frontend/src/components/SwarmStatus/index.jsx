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

const TARGET_ICONS = {
  drone: '✈',
  ship: '⚓',
  tank: '⊞',
  missile_launcher: '↑',
  soldier_unit: '◉',
}

const DRONE_ICONS = {
  recon: '👁',
  combat: '⚡',
  swarm_member: '◈',
}

function remainingRange(drone) {
  const max = drone.max_range_km ?? 0
  const used = drone.range_used_km ?? 0
  return Math.max(0, max - used).toFixed(1)
}

function DetectedContacts({ droneNameOrId, targets }) {
  const contacts = targets.filter(
    t => t.reported_by === droneNameOrId && t.status !== 'destroyed' && t.status !== 'lost'
  )
  if (contacts.length === 0) {
    return <div className="detected-empty">No contacts detected</div>
  }
  return (
    <div className="detected-contacts">
      {contacts.map(t => (
        <div key={t.id} className="detected-item">
          <span className="detected-icon">{TARGET_ICONS[t.type] || '?'}</span>
          <span className="detected-type">{t.type.replace('_', ' ')}</span>
          <span className="detected-conf">{Math.round((t.confidence ?? 0) * 100)}%</span>
          <span className="detected-pos">
            {t.position ? `${t.position.lat.toFixed(2)}°N ${t.position.lon.toFixed(2)}°E` : '—'}
          </span>
          <span className="detected-time" style={{ color: 'var(--text-dim)', fontSize: '0.65rem' }}>
            {t.last_seen ? new Date(t.last_seen).toLocaleTimeString() : '—'}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function SwarmStatus() {
  const swarms = useStore(s => s.swarms)
  const drones = useStore(s => s.drones)
  const targets = useStore(s => s.targets)
  const selectedSwarmId  = useStore(s => s.selectedSwarmId)
  const selectedDroneId  = useStore(s => s.selectedDroneId)
  const selectSwarm      = useStore(s => s.selectSwarm)
  const selectDrone      = useStore(s => s.selectDrone)
  const setCameraCommand = useStore(s => s.setCameraCommand)

  const droneMap = Object.fromEntries(drones.map(d => [d.id, d]))

  const reconDrones = drones.filter(d => d.type === 'recon')

  const STATUS_SORT_ORDER = ['engaging', 'tracking', 'searching', 'returning', 'patrolling', 'idle', 'offline']
  const sortedSwarms = [...swarms].sort((a, b) =>
    STATUS_SORT_ORDER.indexOf(a.status) - STATUS_SORT_ORDER.indexOf(b.status)
  )

  const activeReconDrones = reconDrones.filter(d => d.status !== 'idle')
  const idleReconCount = reconDrones.length - activeReconDrones.length

  return (
    <div className="panel swarm-panel">
      <div className="panel-header">
        <span className="panel-title">◈ SWARM & DRONE STATUS</span>
        <span className="panel-count">{drones.length} TOTAL</span>
      </div>

      <div className="swarm-scroll">

      {/* Combat Swarms */}
      {swarms.length > 0 && (
        <div className="section-label">COMBAT SWARMS</div>
      )}
      {sortedSwarms.map(swarm => {
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
            onClick={() => {
              if (isSelected) { selectSwarm(null); return }
              selectSwarm(swarm.id)
              const positioned = swarmDrones.filter(d => d.position)
              if (positioned.length > 0) {
                const avgLat = positioned.reduce((s, d) => s + d.position.lat, 0) / positioned.length
                const avgLon = positioned.reduce((s, d) => s + d.position.lon, 0) / positioned.length
                setCameraCommand({ ui_subtype: 'fly_to', destination: { lat: avgLat, lon: avgLon } })
              }
            }}
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
                {swarmDrones.filter(d => d.status !== 'idle').map(d => {
                  const isDroneSelected = d.id === selectedDroneId
                  const engagingTargets = isDroneSelected && d.status === 'engaging'
                    ? (swarm.target_ids || []).map(tid => targets.find(t => t.id === tid)).filter(Boolean)
                    : []
                  return (
                    <div key={d.id}>
                      <div
                        className={`drone-item ${isDroneSelected ? 'selected' : ''}`}
                        style={{ cursor: 'pointer' }}
                        onClick={(e) => {
                          e.stopPropagation()
                          const next = isDroneSelected ? null : d.id
                          selectDrone(next)
                          if (next && d.position) {
                            setCameraCommand({ ui_subtype: 'fly_to', destination: { lat: d.position.lat, lon: d.position.lon } })
                          }
                        }}
                      >
                        <span className="drone-icon">{DRONE_ICONS[d.type] || '◈'}</span>
                        <span className="drone-name">{d.name}</span>
                        <span className="drone-status" style={{ color: STATUS_COLORS[d.status] || '#6b7280' }}>
                          {d.status}
                        </span>
                        <span className="drone-battery">🔋{Math.round(d.battery || 0)}%</span>
                        <span className="drone-range">↗{remainingRange(d)} km</span>
                      </div>
                      {isDroneSelected && d.status === 'engaging' && (
                        <div className="recon-detail">
                          <div className="recon-detail-header" style={{ color: STATUS_COLORS.engaging }}>
                            ENGAGING TARGET
                          </div>
                          {engagingTargets.length > 0 ? engagingTargets.map(t => (
                            <div key={t.id} className="detected-item">
                              <span className="detected-icon">{TARGET_ICONS[t.type] || '?'}</span>
                              <span className="detected-type">{t.type.replace('_', ' ')}</span>
                              <span className="detected-conf" style={{ color: 'var(--text-dim)', fontSize: '0.65rem' }}>
                                ID: {t.id}
                              </span>
                            </div>
                          )) : (
                            <div className="detected-empty">Target data unavailable</div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
                {swarmDrones.filter(d => d.status === 'idle').length > 0 && (
                  <div className="drone-item" style={{ color: 'var(--text-dim)', fontSize: 10 }}>
                    {swarmDrones.filter(d => d.status === 'idle').length} drones idle
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}

      {/* Recon Drones */}
      {reconDrones.length > 0 && (
        <div className="section-group">
          <div className="section-label">
            RECONNAISSANCE
            {idleReconCount > 0 && (
              <span className="idle-count"> ({idleReconCount} idle)</span>
            )}
          </div>
          {activeReconDrones.map(d => {
            const isReconSelected = d.id === selectedDroneId
            return (
              <div key={d.id}>
                <div
                  className={`drone-item standalone ${isReconSelected ? 'selected' : ''}`}
                  style={{ cursor: 'pointer' }}
                  onClick={() => {
                    if (isReconSelected) { selectDrone(null); return }
                    selectDrone(d.id)
                    if (d.position) {
                      setCameraCommand({ ui_subtype: 'fly_to', destination: { lat: d.position.lat, lon: d.position.lon } })
                    }
                  }}
                >
                  <span className="drone-icon">👁</span>
                  <span className="drone-name">{d.name}</span>
                  <span className="drone-status" style={{ color: STATUS_COLORS[d.status] || '#6b7280' }}>
                    {d.status}
                  </span>
                  <span className="drone-battery">🔋{Math.round(d.battery || 0)}%</span>
                  <span className="drone-range">↗{remainingRange(d)} km</span>
                </div>
                {d.status === 'tracking' && d.tracking_target_id && (() => {
                  const trackedTarget = targets.find(t => t.id === d.tracking_target_id)
                  return (
                    <div className="recon-detail-header" style={{ color: '#9ca3af', margin: '1px 8px 2px' }}>
                      tracking {trackedTarget ? trackedTarget.type.replace('_', ' ') : 'unknown'} target with id {d.tracking_target_id}
                    </div>
                  )
                })()}
                {isReconSelected && (
                  <div className="recon-detail">
                    <div className="recon-detail-header">
                      DETECTED CONTACTS ({targets.filter(t => t.reported_by === d.name || t.reported_by === d.id).length})
                    </div>
                    <DetectedContacts droneNameOrId={d.name} targets={targets} />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      </div>
    </div>
  )
}
