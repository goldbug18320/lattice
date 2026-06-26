import { useState, useEffect } from 'react'
import { useStore } from '../../store/index.js'

const THREAT_COLORS = {
  high:   { bg: '#7f1d1d', border: '#ef4444', label: '#fca5a5' },
  medium: { bg: '#78350f', border: '#f59e0b', label: '#fde68a' },
  low:    { bg: '#1e3a5f', border: '#60a5fa', label: '#93c5fd' },
}

function Countdown({ expiresAt }) {
  const [remaining, setRemaining] = useState('')

  useEffect(() => {
    const tick = () => {
      const secs = Math.max(0, Math.floor((new Date(expiresAt) - Date.now()) / 1000))
      if (secs === 0) return setRemaining('EXPIRED')
      const m = Math.floor(secs / 60)
      const s = secs % 60
      setRemaining(`${m}:${String(s).padStart(2, '0')}`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [expiresAt])

  const isUrgent = remaining !== 'EXPIRED' && parseInt(remaining) < 1
  return (
    <span style={{ color: isUrgent ? '#ef4444' : '#94a3b8', fontSize: '0.7rem', marginLeft: 6 }}>
      ⏱ {remaining}
    </span>
  )
}

function ThreatBadge({ value, count }) {
  if (!count) return null
  const c = THREAT_COLORS[value] || THREAT_COLORS.low
  return (
    <span style={{
      background: c.bg, border: `1px solid ${c.border}`, color: c.label,
      borderRadius: 3, padding: '1px 6px', fontSize: '0.65rem',
      fontWeight: 700, letterSpacing: '0.05em', marginRight: 4,
    }}>
      {count} {value.toUpperCase()}
    </span>
  )
}

async function sendDecision(approvalId, decision) {
  await fetch(`/api/nlp/${decision}/${approvalId}`, { method: 'POST' })
}

export default function ApprovalBar() {
  const approvals = useStore(s => s.pendingApprovals)
  const [deciding, setDeciding] = useState(null)

  if (!approvals || approvals.length === 0) return null

  const handle = async (id, decision) => {
    setDeciding(id + decision)
    await sendDecision(id, decision)
    setDeciding(null)
  }

  return (
    <div style={{
      background: '#1a0a0a',
      borderTop: '2px solid #7f1d1d',
      borderBottom: '1px solid #374151',
      padding: '6px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
    }}>
      <div style={{ fontSize: '0.65rem', color: '#ef4444', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 2 }}>
        ⚠ ATTACK APPROVAL REQUIRED ({approvals.length})
      </div>
      {approvals.map(a => (
        <div key={a.id} style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: '#1f1717',
          border: '1px solid #4b1c1c',
          borderRadius: 4,
          padding: '5px 10px',
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ color: '#e2e8f0', fontSize: '0.75rem', fontWeight: 600 }}>
              {a.approval_prompt}
            </span>
            <Countdown expiresAt={a.expires_at} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
            {a.threat_summary && Object.entries(a.threat_summary)
              .sort(([a], [b]) => ['high', 'medium', 'low'].indexOf(a) - ['high', 'medium', 'low'].indexOf(b))
              .map(([v, cnt]) => <ThreatBadge key={v} value={v} count={cnt} />)}
          </div>
          <button
            disabled={deciding === a.id + 'approve'}
            onClick={() => handle(a.id, 'approve')}
            style={{
              background: '#14532d', border: '1px solid #16a34a', color: '#86efac',
              borderRadius: 4, padding: '3px 12px', fontSize: '0.72rem',
              fontWeight: 700, cursor: 'pointer', letterSpacing: '0.05em',
            }}
          >
            APPROVE
          </button>
          <button
            disabled={deciding === a.id + 'deny'}
            onClick={() => handle(a.id, 'deny')}
            style={{
              background: '#450a0a', border: '1px solid #dc2626', color: '#fca5a5',
              borderRadius: 4, padding: '3px 12px', fontSize: '0.72rem',
              fontWeight: 700, cursor: 'pointer', letterSpacing: '0.05em',
            }}
          >
            DENY
          </button>
        </div>
      ))}
    </div>
  )
}
