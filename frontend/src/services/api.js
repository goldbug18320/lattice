const BASE = '/api'

async function request(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'API error')
  }
  return res.json()
}

// ─── Reconnaissance ──────────────────────────────────────────────────────────
export const recon = {
  submitFeed: (feed) => request('POST', '/recon/feed', feed),
  getTargets: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request('GET', `/recon/targets${qs ? '?' + qs : ''}`)
  },
  updateTargetStatus: (id, status) =>
    request('PATCH', `/recon/targets/${id}/status?status=${status}`),
  removeTarget: (id) => request('DELETE', `/recon/targets/${id}`),
}

// ─── Swarm Control ───────────────────────────────────────────────────────────
export const swarmApi = {
  listDrones: () => request('GET', '/swarm/drones'),
  listSwarms: () => request('GET', '/swarm/swarms'),
  getSwarm: (id) => request('GET', `/swarm/swarms/${id}`),
  commandSwarm: (swarmId, command) =>
    request('POST', `/swarm/swarms/${swarmId}/command`, command),
  commandDrone: (droneId, command) =>
    request('POST', `/swarm/drones/${droneId}/command`, command),
  getCommandLog: (limit = 50) => request('GET', `/swarm/log?limit=${limit}`),
}

// ─── NLP ─────────────────────────────────────────────────────────────────────
export const nlpApi = {
  command: (text) => request('POST', '/nlp/command', { command: text }),
  history: (limit = 50) => request('GET', `/nlp/history?limit=${limit}`),
}

// ─── Full State ───────────────────────────────────────────────────────────────
export const stateApi = {
  getFullState: () => request('GET', '/state'),
}
