import { create } from 'zustand'

export const useStore = create((set, get) => ({
  // Battlefield state
  drones: [],
  targets: [],
  swarms: [],
  pendingApprovals: [],
  commandLog: [],
  lastUpdate: null,

  // UI state
  selectedTargetId: null,
  selectedSwarmId: null,
  selectedDroneId: null,
  showTargetList: true,
  showSwarmStatus: true,
  showCommandLog: true,
  mapView: '3d', // '3d' | '2d'

  // WebSocket
  wsConnected: false,
  wsStatus: 'disconnected',

  cameraCommand: null,

  // Asset Palette placement mode: null | { kind: 'drone'|'target', model?, type?, label, alt? }
  placementMode: null,

  // Actions
  setWsConnected: (connected) => set({ wsConnected: connected, wsStatus: connected ? 'connected' : 'disconnected' }),
  setWsStatus: (status) => set({ wsStatus: status }),

  updateBattlefieldState: (state) => set({
    drones: state.drones || [],
    targets: state.targets || [],
    swarms: state.swarms || [],
    pendingApprovals: state.pending_approvals || [],
    lastUpdate: state.timestamp,
  }),

  addCommandLog: (entry) => set((s) => ({
    commandLog: [entry, ...s.commandLog].slice(0, 100),
  })),

  selectTarget: (id) => set({ selectedTargetId: id }),
  selectSwarm: (id) => set({ selectedSwarmId: id }),
  selectDrone: (id) => set({ selectedDroneId: id }),

  setCameraCommand: (cmd) => set({ cameraCommand: cmd }),
  setPlacementMode: (mode) => set({ placementMode: mode }),

  togglePanel: (panel) => set((s) => ({ [panel]: !s[panel] })),
}))
