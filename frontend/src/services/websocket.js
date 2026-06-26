import { useStore } from '../store/index.js'

let socket = null
let reconnectTimeout = null

export function connectWebSocket() {
  const { setWsConnected, setWsStatus, updateBattlefieldState } = useStore.getState()

  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return
  }

  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = window.location.host
  const url = `${protocol}://${host}/ws`

  setWsStatus('connecting')
  socket = new WebSocket(url)

  socket.onopen = () => {
    setWsConnected(true)
    clearTimeout(reconnectTimeout)
  }

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      updateBattlefieldState(data)
    } catch (e) {
      console.error('WS parse error:', e)
    }
  }

  socket.onclose = () => {
    setWsConnected(false)
    setWsStatus('reconnecting')
    reconnectTimeout = setTimeout(connectWebSocket, 3000)
  }

  socket.onerror = () => {
    setWsStatus('error')
    socket.close()
  }
}

export function disconnectWebSocket() {
  clearTimeout(reconnectTimeout)
  if (socket) {
    socket.close()
    socket = null
  }
}
