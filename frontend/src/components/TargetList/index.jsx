import { useStore } from '../../store/index.js'
import { swarmApi } from '../../services/api.js'


const TYPE_ICONS = {
  drone: '✈',
  ship: '⚓',
  tank: '⊞',
  missile_launcher: '↑',
}

const TYPE_COLORS = {
  drone: '#f87171',
  ship: '#fb923c',
  tank: '#f87171',
  missile_launcher: '#e879f9',
}

const STATUS_BADGES = {
  active: { label: 'ACTIVE', color: '#ef4444' },
  tracked: { label: 'TRACKED', color: '#f59e0b' },
  engaged: { label: 'ENGAGED', color: '#f97316' },
  destroyed: { label: 'DESTROYED', color: '#6b7280' },
  lost: { label: 'LOST', color: '#4b5563' },
}

export default function TargetList() {
  const targets = useStore(s => s.targets)
  const swarms = useStore(s => s.swarms)
  const selectedTargetId = useStore(s => s.selectedTargetId)
  const selectTarget = useStore(s => s.selectTarget)

  const selectSwarm = useStore(s => s.selectSwarm)

  const activeTargets = targets.filter(t => !['destroyed', 'lost'].includes(t.status))

  const grouped = activeTargets.reduce((acc, t) => {
    acc[t.type] = acc[t.type] || []
    acc[t.type].push(t)
    return acc
  }, {})

  const engageTarget = async (targetId) => {
    const idleSwarm = swarms.find(s => s.status === 'idle') || swarms[0]
    if (!idleSwarm) return alert('No swarms available')
    await swarmApi.commandSwarm(idleSwarm.id, {
      command_type: 'attack',
      target_ids: [targetId],
      objective: `Engage target ${targetId}`,
      priority: 9,
    })
    selectSwarm(idleSwarm.id)
  }

  return (
    <div className="panel target-panel">
      <div className="panel-header">
        <span className="panel-title">🎯 ENEMY TARGETS</span>
        <span className="panel-count threat">{activeTargets.length} ACTIVE</span>
      </div>

      {activeTargets.length === 0 && (
        <div className="empty-state">No active targets detected</div>
      )}

      {Object.entries(grouped).map(([type, items]) => (
        <div key={type} className="target-group">
          <div className="target-group-header" style={{ color: TYPE_COLORS[type] || '#f87171' }}>
            {TYPE_ICONS[type]} {type.replace('_', ' ').toUpperCase()} ({items.length})
          </div>
          {items.map(target => {
            const badge = STATUS_BADGES[target.status] || STATUS_BADGES.active
            const isSelected = target.id === selectedTargetId

            return (
              <div
                key={target.id}
                className={`target-item ${isSelected ? 'selected' : ''}`}
                onClick={() => selectTarget(isSelected ? null : target.id)}
              >
                <div className="target-row1">
                  <span className="target-type-icon" style={{ color: TYPE_COLORS[type] }}>
                    {TYPE_ICONS[type]}
                  </span>
                  <span className="target-coords">
                    {target.position.lat.toFixed(4)}°, {target.position.lon.toFixed(4)}°
                  </span>
                  <span className="target-badge" style={{ color: badge.color }}>
                    {badge.label}
                  </span>
                </div>
                <div className="target-row2">
                  <span className="target-conf">
                    Conf: {Math.round(target.confidence * 100)}%
                    <span className="conf-bar">
                      <span className="conf-fill" style={{ width: `${target.confidence * 100}%` }} />
                    </span>
                  </span>
                  {target.speed > 0 && (
                    <span className="target-speed">{Math.round(target.speed)}m/s {target.heading.toFixed(0)}°</span>
                  )}
                </div>
                {isSelected && (
                  <div className="target-actions">
                    <button className="target-btn attack" onClick={e => { e.stopPropagation(); engageTarget(target.id) }}>
                      ⚡ ENGAGE
                    </button>
                    <button className="target-btn track" onClick={e => { e.stopPropagation() }}>
                      👁 TRACK
                    </button>
                    {target.notes && <div className="target-notes">{target.notes}</div>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
