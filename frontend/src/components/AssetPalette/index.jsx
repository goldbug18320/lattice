import { useState } from 'react'
import { useStore } from '../../store/index.js'

const FRIENDLY = [
  { label: 'MQ-9 Recon',   kind: 'drone', model: 'mq9_recon',   color: '#0abfff' },
  { label: 'Scout Recon',  kind: 'drone', model: 'scout_recon', color: '#3c78ff' },
  { label: 'FPV Combat',   kind: 'drone', model: 'fpv_combat',  color: '#32dc32' },
  { label: 'Altius-600M',  kind: 'drone', model: 'altius_600m', color: '#28c850' },
]

const ENEMY = [
  { label: 'Attack Drone', kind: 'target', type: 'drone',            alt: 3000, color: '#c81e1e' },
  { label: 'FPV Drone',    kind: 'target', type: 'drone',            alt: 50,   color: '#e63030' },
  { label: 'Tank',         kind: 'target', type: 'tank',             alt: 0,    color: '#e61414' },
  { label: 'Ship',         kind: 'target', type: 'ship',             alt: 0,    color: '#f0461e' },
  { label: 'Missile Lnchr',kind: 'target', type: 'missile_launcher', alt: 0,    color: '#d20a50' },
  { label: 'Soldiers',     kind: 'target', type: 'soldier_unit',     alt: 0,    color: '#af1429' },
]

const KEY = (item) => item.model ?? `${item.type}-${item.alt}`

export default function AssetPalette() {
  const [collapsed, setCollapsed] = useState(false)
  const placementMode  = useStore(s => s.placementMode)
  const setPlacementMode = useStore(s => s.setPlacementMode)

  const toggle = (item) => {
    const active = placementMode && KEY(placementMode) === KEY(item)
    setPlacementMode(active ? null : { ...item })
  }

  const isActive = (item) => placementMode && KEY(placementMode) === KEY(item)

  const s = {
    panel: {
      position: 'absolute', left: 8, top: 8, zIndex: 10,
      background: 'rgba(10,14,26,0.92)', border: '1px solid #1e3a5f',
      borderRadius: 4, width: collapsed ? 32 : 152, overflow: 'hidden',
      transition: 'width 0.15s', fontFamily: 'monospace',
    },
    header: {
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '4px 8px', cursor: 'pointer', borderBottom: '1px solid #1e3a5f',
    },
    badge: { color: '#7ab3d4', fontSize: 10, letterSpacing: 1 },
    chevron: { color: '#7ab3d4', fontSize: 11 },
    hint: {
      padding: '4px 8px', color: '#f59e0b', fontSize: 9,
      borderBottom: '1px solid #1e3a5f', lineHeight: 1.5,
    },
    sectionLabel: (color) => ({ padding: '3px 8px 1px', color, fontSize: 9, letterSpacing: 1 }),
    item: (color, active) => ({
      padding: '3px 8px', cursor: 'pointer', fontSize: 10,
      color: active ? '#f59e0b' : color,
      background: active ? 'rgba(245,158,11,0.15)' : 'transparent',
    }),
  }

  return (
    <div style={s.panel}>
      <div style={s.header} onClick={() => setCollapsed(c => !c)}>
        {!collapsed && <span style={s.badge}>ASSETS</span>}
        <span style={s.chevron}>{collapsed ? '▶' : '◀'}</span>
      </div>

      {!collapsed && (
        <>
          {placementMode && (
            <div style={s.hint}>
              PLACING: {placementMode.label}<br />
              <span style={{ color: '#6b7280' }}>Click map • ESC cancel</span>
            </div>
          )}

          <div style={s.sectionLabel('#4ade80')}>FRIENDLY</div>
          {FRIENDLY.map(item => (
            <div key={item.model} style={s.item(item.color, isActive(item))} onClick={() => toggle(item)}>
              + {item.label}
            </div>
          ))}

          <div style={{ ...s.sectionLabel('#ef4444'), marginTop: 4 }}>ENEMY</div>
          {ENEMY.map(item => (
            <div key={KEY(item)} style={s.item(item.color, isActive(item))} onClick={() => toggle(item)}>
              + {item.label}
            </div>
          ))}
        </>
      )}
    </div>
  )
}
