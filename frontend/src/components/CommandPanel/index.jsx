import { useStore } from '../../store/index.js'
import { nlpApi, swarmApi } from '../../services/api.js'

export default function CommandPanel() {
  const swarms = useStore(s => s.swarms)

  const swarmGroups = [
    { label: 'FPV Swarms',  prefix: 'FPV', icon: '⚡', color: '#3b82f6' },
    { label: 'ALT Swarms',  prefix: 'ALT', icon: '🚀', color: '#06b6d4' },
  ].map(g => ({
    ...g,
    swarms: swarms.filter(s => s.name.startsWith(g.prefix)),
  })).filter(g => g.swarms.length > 0)

  const groupCommand = async (groupSwarms, commandType) => {
    if (commandType === 'attack') {
      const names = groupSwarms.map(s => s.name).join(' and ')
      await nlpApi.command(`Order ${names} to attack all active enemy targets with maximum priority`)
      return
    }

    const label = `${commandType} command`
    await Promise.all(groupSwarms.map(s =>
      swarmApi.commandSwarm(s.id, {
        command_type: commandType,
        target_ids: [],
        objective: label,
        priority: 5,
      })
    ))
  }

  return (
    <div className="panel command-panel">
      <div className="panel-header">
        <span className="panel-title">⌨ SWARM CONTROLS</span>
      </div>

      {swarmGroups.length > 0 && (
        <div className="swarm-controls">
          <div className="swarm-groups">
            {swarmGroups.map(group => (
              <div key={group.prefix} className="swarm-group-row">
                <span className="swarm-group-label" style={{ color: group.color }}>
                  {group.icon} {group.label} <span className="swarm-group-count">×{group.swarms.length}</span>
                </span>
                <div className="swarm-btns">
                  {[
                    { type: 'locate', label: '🔍' },
                    { type: 'track',  label: '👁' },
                    { type: 'attack', label: '⚡' },
                    { type: 'return', label: '↩' },
                  ].map(({ type, label }) => (
                    <button
                      key={type}
                      className={`action-btn action-${type}`}
                      title={`${type.toUpperCase()} all ${group.label}`}
                      onClick={() => groupCommand(group.swarms, type)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
