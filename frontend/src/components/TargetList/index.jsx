import { useState } from 'react'
import { useStore } from '../../store/index.js'
import { nlpApi } from '../../services/api.js'


const TYPE_ICONS = {
  drone: '✈',
  ship: '⚓',
  tank: '⊞',
  missile_launcher: '↑',
  soldier_unit: '◉',
}

const TYPE_COLORS = {
  drone: '#f87171',
  ship: '#fb923c',
  tank: '#f87171',
  missile_launcher: '#e879f9',
  soldier_unit: '#dc2626',
}

const STATUS_BADGES = {
  active: { label: 'ACTIVE', color: '#ef4444' },
  tracked: { label: 'TRACKED', color: '#f59e0b' },
  engaged: { label: 'ENGAGED', color: '#f97316' },
  destroyed: { label: 'DESTROYED', color: '#6b7280' },
  lost: { label: 'LOST', color: '#4b5563' },
}

const THREAT_COLORS = {
  high:   '#ef4444',
  medium: '#f59e0b',
  low:    '#60a5fa',
}

export default function TargetList() {
  const targets = useStore(s => s.targets)
  const swarms = useStore(s => s.swarms)
  const selectedTargetId = useStore(s => s.selectedTargetId)
  const selectTarget = useStore(s => s.selectTarget)
  const setCameraCommand = useStore(s => s.setCameraCommand)
  const selectSwarm = useStore(s => s.selectSwarm)
  const selectDrone = useStore(s => s.selectDrone)
  const disengageMessages = useStore(s => s.disengageMessages)
  const setDisengageMessage = useStore(s => s.setDisengageMessage)

  // Inline error/info state for ENGAGE/TRACK buttons: { [targetId]: string | null }
  const [engageErrors, setEngageErrors] = useState({})
  const [trackErrors, setTrackErrors] = useState({})
  const [trackInfos, setTrackInfos] = useState({})

  const activeTargets = targets.filter(t => !['destroyed', 'lost'].includes(t.status) && t.affiliation !== 'friendly')

  const grouped = activeTargets.reduce((acc, t) => {
    acc[t.type] = acc[t.type] || []
    acc[t.type].push(t)
    return acc
  }, {})

  // Feature 22: the name of the swarm currently engaging a target, derived live
  // from battlefield state — always visible under the button for as long as the
  // target stays engaged, not just right after the approval click.
  const engagingSwarmName = (targetId) => {
    const swarm = swarms.find(s => s.status === 'engaging' && s.target_ids?.includes(targetId))
    return swarm ? swarm.name : 'a combat swarm'
  }

  // ENGAGE routes through HITL — the LLM classifies the target and creates a
  // pending approval; the proposed swarm is pre-selected in the status panel
  // so the operator sees which swarm will be tasked (Feature 13 + Feature 15).
  // Once approved, the target's button changes from ENGAGE to DISENGAGE (Feature 32).
  const engageTarget = async (targetId) => {
    setEngageErrors(prev => ({ ...prev, [targetId]: null }))
    setDisengageMessage(targetId, null)
    try {
      const result = await nlpApi.command(`engage and attack target with id ${targetId}`)
      if (result.action?.type === 'no_swarm_in_range') {
        setEngageErrors(prev => ({ ...prev, [targetId]: 'No combat swarm in range' }))
      } else if (result.action?.type === 'request_approval') {
        const proposedSwarmId = result.action?.proposed_action?.swarm_id
        if (proposedSwarmId) selectSwarm(proposedSwarmId)
      }
    } catch (e) {
      console.error('Engage failed:', e)
    }
  }

  // DISENGAGE (Feature 32): clicking this only queues a confirmation prompt in
  // the bottom Approval Bar (§9.3.1) — the same area used for HITL attack
  // approvals. No LLM call, but nothing is recalled until the operator confirms
  // there; the ApprovalBar writes the outcome message into the store once decided.
  const disengageTarget = async (targetId) => {
    setEngageErrors(prev => ({ ...prev, [targetId]: null }))
    try {
      await nlpApi.command(`disengage target with id ${targetId}`)
    } catch (e) {
      console.error('Disengage failed:', e)
    }
  }

  // TRACK routes through HITL with a recon drone (Feature 24). On no_recon_in_range show
  // an inline error. On already_tracked (Feature 28) show an info message naming the current
  // tracking drone — no new assignment. On approval pre-select the chosen drone.
  const trackTarget = async (targetId) => {
    setTrackErrors(prev => ({ ...prev, [targetId]: null }))
    setTrackInfos(prev => ({ ...prev, [targetId]: null }))
    try {
      const result = await nlpApi.command(`track target with id ${targetId}`)
      if (result.action?.type === 'no_recon_in_range') {
        setTrackErrors(prev => ({ ...prev, [targetId]: 'No reconnaissance drone in range' }))
      } else if (result.action?.type === 'already_tracked') {
        setTrackInfos(prev => ({ ...prev, [targetId]: result.action.explanation }))
      } else if (result.action?.type === 'request_approval') {
        const proposedDroneId = result.action?.proposed_action?.drone_id
        if (proposedDroneId) selectDrone(proposedDroneId)
      }
    } catch (e) {
      console.error('Track failed:', e)
    }
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
                onClick={() => {
                  const next = isSelected ? null : target.id
                  selectTarget(next)
                  if (next && target.position) {
                    setCameraCommand({ ui_subtype: 'fly_to', destination: { lat: target.position.lat, lon: target.position.lon } })
                  }
                }}
              >
                <div className="target-row1">
                  <span className="target-type-icon" style={{ color: TYPE_COLORS[type] }}>
                    {TYPE_ICONS[type]}
                  </span>
                  {target.threat_value && (
                    <span className="threat-badge" style={{ color: THREAT_COLORS[target.threat_value] }}>
                      {target.threat_value.toUpperCase()}
                    </span>
                  )}
                  <span className="target-coords">
                    {target.position.lat.toFixed(4)}°, {target.position.lon.toFixed(4)}°
                  </span>
                  <span className="target-badge" style={{ color: badge.color }}>
                    {badge.label}
                  </span>
                </div>
                <div className="target-subtitle">
                  <span className="target-subtitle-type" style={{ color: TYPE_COLORS[type] }}>
                    {type.replace('_', ' ').toUpperCase()}
                  </span>
                  <span className="target-subtitle-sep">·</span>
                  <span className="target-subtitle-id">{target.id.slice(0, 8).toUpperCase()}</span>
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
                    {target.status === 'engaged' ? (
                      <button
                        className="target-btn disengage"
                        onClick={e => { e.stopPropagation(); disengageTarget(target.id) }}
                      >
                        ⨯ DISENGAGE
                      </button>
                    ) : (
                      <button
                        className="target-btn attack"
                        onClick={e => { e.stopPropagation(); engageTarget(target.id) }}
                      >
                        ⚡ ENGAGE
                      </button>
                    )}
                    <button
                      className="target-btn track"
                      onClick={e => { e.stopPropagation(); trackTarget(target.id) }}
                    >
                      👁 TRACK
                    </button>
                    {engageErrors[target.id] && (
                      <div className="engage-error">{engageErrors[target.id]}</div>
                    )}
                    {target.status === 'engaged' ? (
                      // Feature 22: always-visible message naming the engaging swarm,
                      // derived from live state — not a one-time toast.
                      <div className="engage-info">Engaged by {engagingSwarmName(target.id)}</div>
                    ) : disengageMessages[target.id] && (
                      // Feature 32: one-time confirmation message shown after the
                      // operator approves/denies the disengage prompt in the Approval Bar.
                      <div className="engage-info">{disengageMessages[target.id]}</div>
                    )}
                    {trackErrors[target.id] && (
                      <div className="track-error">{trackErrors[target.id]}</div>
                    )}
                    {trackInfos[target.id] && (
                      <div className="track-info">{trackInfos[target.id]}</div>
                    )}
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
