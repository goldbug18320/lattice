import { useState, useRef, useEffect } from 'react'
import { useStore } from '../../store/index.js'
import { nlpApi, swarmApi } from '../../services/api.js'

const QUICK_COMMANDS = [
  { label: '🔍 Scout Area', cmd: 'Send FPV swarms to search the area and locate all enemy targets' },
  { label: '🎯 Attack All', cmd: 'Order all available swarms to attack all active enemy targets with high priority' },
  { label: '👁 Track Targets', cmd: 'Assign ALT swarms to track all enemy ships and tanks' },
  { label: '↩ RTB All', cmd: 'Recall all swarms back to base immediately' },
  { label: '📡 Status', cmd: 'Give me a full tactical status report' },
]

export default function CommandPanel() {
  const [input, setInput] = useState('')
  const [log, setLog] = useState([])
  const logRef = useRef(null)

  const nlpProcessing = useStore(s => s.nlpProcessing)
  const lastNlpResponse = useStore(s => s.lastNlpResponse)
  const setNlpProcessing = useStore(s => s.setNlpProcessing)
  const setLastNlpResponse = useStore(s => s.setLastNlpResponse)
  const setCameraCommand = useStore(s => s.setCameraCommand)
  const swarms = useStore(s => s.swarms)
  const targets = useStore(s => s.targets)

  const appendLog = (entry) => setLog(prev => [...prev.slice(-99), entry])

  const submit = async (cmd) => {
    const text = (cmd || input).trim()
    if (!text) return
    setInput('')
    appendLog({ type: 'user', text, ts: new Date().toLocaleTimeString() })
    setNlpProcessing(true)

    try {
      const result = await nlpApi.command(text)
      setLastNlpResponse(result)
      // Route ui_command to the map camera controller
      if (result.action?.type === 'ui_command') {
        setCameraCommand(result.action)
      }
      // Determine display text and log entry type
      let responseText = result.explanation || result.interpretation
      let logType = 'ai'
      if (result.action?.type === 'request_approval') {
        responseText = `⚠ APPROVAL REQUIRED — ${result.action.approval_prompt}`
        logType = 'hitl'
      } else if (result.action?.type === 'request_status') {
        responseText = result.action.status_text || result.explanation
      }
      appendLog({
        type: logType,
        text: responseText,
        detail: result.action,
        ts: new Date().toLocaleTimeString(),
      })
    } catch (e) {
      appendLog({ type: 'error', text: `Error: ${e.message}`, ts: new Date().toLocaleTimeString() })
    } finally {
      setNlpProcessing(false)
    }
  }

  // Group swarms by model prefix for compact controls
  const swarmGroups = [
    { label: 'FPV Swarms',  prefix: 'FPV', icon: '⚡', color: '#10b981' },
    { label: 'ALT Swarms',  prefix: 'ALT', icon: '🚀', color: '#06b6d4' },
  ].map(g => ({
    ...g,
    swarms: swarms.filter(s => s.name.startsWith(g.prefix)),
  })).filter(g => g.swarms.length > 0)

  const groupCommand = async (groupSwarms, commandType) => {
    // Attack must go through HITL approval — route via NLP (§6.8, Feature 13)
    if (commandType === 'attack') {
      const names = groupSwarms.map(s => s.name).join(' and ')
      try {
        const result = await nlpApi.command(
          `Order ${names} to attack all active enemy targets with maximum priority`
        )
        let responseText = result.explanation || result.interpretation
        let logType = 'ai'
        if (result.action?.type === 'request_approval') {
          responseText = `⚠ APPROVAL REQUIRED — ${result.action.approval_prompt}`
          logType = 'hitl'
        }
        appendLog({ type: logType, text: responseText, ts: new Date().toLocaleTimeString() })
      } catch (e) {
        appendLog({ type: 'error', text: `Failed: ${e.message}`, ts: new Date().toLocaleTimeString() })
      }
      return
    }

    // Non-attack commands (locate, track, patrol, return) execute immediately
    const label = `${commandType} command`
    try {
      await Promise.all(groupSwarms.map(s =>
        swarmApi.commandSwarm(s.id, {
          command_type: commandType,
          target_ids: [],
          objective: label,
          priority: 5,
        })
      ))
      appendLog({ type: 'system', text: `✓ ${label} → ${groupSwarms.length} swarms`, ts: new Date().toLocaleTimeString() })
    } catch (e) {
      appendLog({ type: 'error', text: `Failed: ${e.message}`, ts: new Date().toLocaleTimeString() })
    }
  }

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [log])

  return (
    <div className="panel command-panel">
      <div className="panel-header">
        <span className="panel-title">⌨ OPERATOR COMMAND INTERFACE</span>
      </div>

      <div className="cmd-top-row">
        {/* Quick Actions */}
        <div className="quick-actions">
          {QUICK_COMMANDS.map(q => (
            <button key={q.label} className="quick-btn" onClick={() => submit(q.cmd)} disabled={nlpProcessing}>
              {q.label}
            </button>
          ))}
        </div>

        {/* Model-Grouped Swarm Controls */}
        {swarmGroups.length > 0 && (
          <div className="swarm-controls">
            <div className="section-label">SWARM CONTROLS</div>
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

      {/* NLP Command Log */}
      <div className="cmd-log" ref={logRef}>
        {log.length === 0 && (
          <div className="log-empty">Type a natural language command or use quick actions above...</div>
        )}
        {log.map((entry, i) => (
          <div key={i} className={`log-entry log-${entry.type}`}>
            <span className="log-ts">{entry.ts}</span>
            {entry.type === 'user' && <span className="log-prefix">▶ </span>}
            {entry.type === 'ai' && <span className="log-prefix">🤖 </span>}
            {entry.type === 'hitl' && <span className="log-prefix">⚠ </span>}
            {entry.type === 'system' && <span className="log-prefix">⚙ </span>}
            {entry.type === 'error' && <span className="log-prefix">✗ </span>}
            <span className="log-text">{entry.text}</span>
          </div>
        ))}
        {nlpProcessing && (
          <div className="log-entry log-ai">
            <span className="log-prefix">🤖 </span>
            <span className="log-text processing">Processing command...</span>
          </div>
        )}
      </div>

      {/* NLP Text Input */}
      <div className="cmd-input-row">
        <input
          className="cmd-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !nlpProcessing && submit()}
          placeholder="Enter tactical or UI command in natural language..."
          disabled={nlpProcessing}
          autoFocus
        />
        <button
          className="cmd-submit"
          onClick={() => submit()}
          disabled={nlpProcessing || !input.trim()}
        >
          {nlpProcessing ? '⏳' : '▶ SEND'}
        </button>
      </div>
    </div>
  )
}
