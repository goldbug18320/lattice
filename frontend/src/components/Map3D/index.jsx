import { useEffect, useRef, useCallback, useState } from 'react'
import { useStore } from '../../store/index.js'
import { assetsApi } from '../../services/api.js'

// Target type icons/colors — all enemy assets rendered in red shades (spec v1.7)
const TARGET_CONFIG = {
  drone:            { color: [200, 30,  30,  220], label: '✈ DRONE',  scale: 1.2 },  // dark red
  ship:             { color: [240, 70,  30,  220], label: '⚓ SHIP',   scale: 1.8 },  // red-orange
  tank:             { color: [230, 20,  20,  220], label: '⊞ TANK',   scale: 1.4 },  // bright red
  missile_launcher: { color: [210, 10,  80,  220], label: '↑ MLRS',   scale: 1.6 },  // magenta-red
  soldier_unit:     { color: [175, 20,  45,  220], label: '◉ SOLDIER', scale: 1.0 },  // crimson
}

// Config keyed by drone.model first, then drone.type as fallback
// Friendly: recon = blue shades, combat = green shades (spec v1.7)
const DRONE_CONFIG = {
  // model-specific
  mq9_recon:    { color: [0,   200, 255, 220], label: '👁 MQ-9',   size: 14 },  // cyan-blue
  scout_recon:  { color: [60,  120, 255, 220], label: '📡 SCOUT',  size: 10 },  // blue
  fpv_combat:   { color: [50,  220,  50, 220], label: '⚡ FPV',    size: 8  },  // green
  altius_600m:  { color: [40,  200,  80, 220], label: '🚀 ALT',    size: 8  },  // green-cyan
  // type fallback
  recon:        { color: [0,   200, 255, 220], label: '👁 RECON',  size: 12 },
  combat:       { color: [50,  220,  50, 220], label: '⚡ COMBAT', size: 10 },
  swarm_member: { color: [50,  220,  50, 220], label: '◈ SWARM',  size: 8  },
}

const STATUS_COLORS = {
  idle:       [150, 150, 150],
  patrolling: [0,   180, 255],
  searching:  [255, 200, 0  ],
  tracking:   [255, 140, 0  ],
  engaging:   [255, 50,  50 ],
  returning:  [0,   255, 150],
  offline:    [80,  80,  80 ],
}

// Taiwan island-wide view
const TAIWAN_HOME = { lon: 121.0, lat: 23.8, altM: 450_000 }

// Feature 21: geographic land/sea heuristic for the Taiwan theater.
// Using terrain height from sampleTerrainMostDetailed is unreliable because the
// Taiwan Strait is shallow (~60-80 m) and Cesium may report near-zero heights there.
function likelySea(lon, lat) {
  if (lon >= 119.4 && lon <= 120.1 && lat >= 22.0 && lat <= 26.5) return true  // Taiwan Strait
  if (lon > 122.0) return true                                                   // Open Pacific east of Taiwan
  if (lat < 21.5 && lon > 116.0) return true                                    // South China Sea / Bashi Channel
  return false
}

export default function Map3D() {
  const viewerRef    = useRef(null)
  const containerRef = useRef(null)
  const entityMapRef = useRef({ drones: {}, targets: {} })
  // Drag state: tracks in-progress drag-and-drop reposition operations
  const dragRef = useRef({ active: false, entity: null, type: null, id: null, subtype: null, moved: false, originalPosition: null })
  // Tracks whether a drag just completed so LEFT_CLICK can ignore the synthetic click
  const dragJustFinishedRef = useRef(false)
  const [viewerReady, setViewerReady] = useState(false)

  const drones           = useStore(s => s.drones)
  const targets          = useStore(s => s.targets)
  const selectedTargetId = useStore(s => s.selectedTargetId)
  const selectedSwarmId  = useStore(s => s.selectedSwarmId)
  const selectedDroneId  = useStore(s => s.selectedDroneId)
  const selectTarget     = useStore(s => s.selectTarget)
  const selectDrone      = useStore(s => s.selectDrone)
  const cameraCommand    = useStore(s => s.cameraCommand)
  const setCameraCommand = useStore(s => s.setCameraCommand)
  const placementMode    = useStore(s => s.placementMode)

  // ── Initialize Cesium viewer ────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    let viewer = null
    const init = async () => {
      const Cesium = (await import('cesium')).default || (await import('cesium'))
      if (cancelled) return

      const terrainProvider = await Cesium.createWorldTerrainAsync()
        .catch(() => new Cesium.EllipsoidTerrainProvider())
      if (cancelled) return

      viewer = new Cesium.Viewer(containerRef.current, {
        terrainProvider,
        baseLayerPicker:       false,
        geocoder:              false,
        homeButton:            false,
        sceneModePicker:       false,
        navigationHelpButton:  false,
        animation:             false,
        timeline:              false,
        fullscreenButton:      false,
        infoBox:               false,
        selectionIndicator:    false,
        creditContainer:       document.createElement('div'),
      })

      viewer.scene.skyAtmosphere.show = true
      viewer.scene.globe.enableLighting = true
      viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#0a0e1a')

      // Default camera: Taiwan island-wide tactical view
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(TAIWAN_HOME.lon, TAIWAN_HOME.lat, TAIWAN_HOME.altM),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-60), roll: 0 },
      })

      viewerRef.current = viewer
      setViewerReady(true)

      const ET = Cesium.ScreenSpaceEventType
      const handler = viewer.screenSpaceEventHandler

      // ── Drag: LEFT_DOWN — detect entity under cursor ────────────────────────
      handler.setInputAction((event) => {
        const picked = viewer.scene.pick(event.position)
        if (picked?.id?._lattice_type) {
          const latticeType = picked.id._lattice_type
          const latticeId   = picked.id._lattice_id
          // Capture the target sub-type (ship/tank/etc.) for terrain validation on drop
          const subtype = latticeType === 'target'
            ? (useStore.getState().targets.find(t => t.id === latticeId)?.type ?? null)
            : null
          dragRef.current = {
            active: true,
            entity: picked.id,
            type: latticeType,
            id: latticeId,
            subtype,
            moved: false,
            originalPosition: picked.id.position.getValue(Cesium.JulianDate.now()),
          }
        }
      }, ET.LEFT_DOWN)

      // ── Drag: MOUSE_MOVE — slide entity across globe surface ────────────────
      handler.setInputAction((event) => {
        const drag = dragRef.current
        if (!drag.active || !drag.entity) return
        drag.moved = true
        // Disable camera pan/rotate while dragging
        viewer.scene.screenSpaceCameraController.enableRotate = false
        viewer.scene.screenSpaceCameraController.enableTranslate = false
        viewer.scene.screenSpaceCameraController.enableZoom = false

        const ray = viewer.camera.getPickRay(event.endPosition)
        const globePos = viewer.scene.globe.pick(ray, viewer.scene)
        if (globePos) {
          const globeCarto = Cesium.Cartographic.fromCartesian(globePos)
          const curPos = drag.entity.position.getValue(Cesium.JulianDate.now())
          const curCarto = Cesium.Cartographic.fromCartesian(curPos)
          // Maintain the entity's current altitude while updating lat/lon
          drag.entity.position.setValue(
            Cesium.Cartesian3.fromRadians(globeCarto.longitude, globeCarto.latitude, curCarto.height)
          )
        }
      }, ET.MOUSE_MOVE)

      // ── Drag: LEFT_UP — validate terrain constraint then persist ───────────────
      handler.setInputAction(() => {
        const drag = dragRef.current
        viewer.scene.screenSpaceCameraController.enableRotate = true
        viewer.scene.screenSpaceCameraController.enableTranslate = true
        viewer.scene.screenSpaceCameraController.enableZoom = true

        if (drag.active && drag.moved && drag.entity) {
          dragJustFinishedRef.current = true
          const cart = drag.entity.position.getValue(Cesium.JulianDate.now())
          if (cart) {
            const carto = Cesium.Cartographic.fromCartesian(cart)
            const position = {
              lat: Cesium.Math.toDegrees(carto.latitude),
              lon: Cesium.Math.toDegrees(carto.longitude),
              alt: carto.height,
            }

            // Feature 21: land/sea placement constraints
            // tanks, missile launchers, soldiers → land (h ≥ 0)
            // ships → sea (h < 0)
            // drones → unconstrained
            const LAND_TYPES = new Set(['tank', 'missile_launcher', 'soldier_unit'])
            const needsLand = LAND_TYPES.has(drag.subtype)
            const needsSea  = drag.subtype === 'ship'

            const persist = () => {
              const updateFn = drag.type === 'drone'
                ? assetsApi.updateDronePosition(drag.id, position)
                : assetsApi.updateTargetPosition(drag.id, position)
              updateFn.then(() => assetsApi.saveConfig()).catch(console.error)
            }

            const revert = () => {
              if (drag.originalPosition) drag.entity.position.setValue(drag.originalPosition)
              drag.entity.point.outlineColor.setValue(Cesium.Color.RED)
              drag.entity.point.outlineWidth.setValue(5)
              setTimeout(() => {
                drag.entity.point.outlineColor.setValue(Cesium.Color.fromBytes(255, 200, 0, 200))
                drag.entity.point.outlineWidth.setValue(1)
              }, 800)
            }

            if (needsLand || needsSea) {
              const sea = likelySea(position.lon, position.lat)
              if ((needsLand && sea) || (needsSea && !sea)) revert()
              else persist()
            } else {
              persist()
            }
          }
        }
        dragRef.current = { active: false, entity: null, type: null, id: null, subtype: null, moved: false, originalPosition: null }
      }, ET.LEFT_UP)

      // ── RIGHT_CLICK — remove entity from scenario ───────────────────────────
      handler.setInputAction((event) => {
        const picked = viewer.scene.pick(event.position)
        if (picked?.id?._lattice_type) {
          const type = picked.id._lattice_type
          const id   = picked.id._lattice_id
          const label = type === 'drone' ? 'drone' : 'target'
          if (window.confirm(`Remove this ${label} from the scenario?`)) {
            const del = type === 'drone'
              ? assetsApi.deleteDrone(id)
              : assetsApi.deleteTarget(id)
            del.catch(console.error)
          }
        }
      }, ET.RIGHT_CLICK)

      // ── LEFT_CLICK — placement mode OR entity selection ─────────────────────
      handler.setInputAction((click) => {
        // If a drag just completed, consume the synthetic click without selecting
        if (dragJustFinishedRef.current) {
          dragJustFinishedRef.current = false
          return
        }

        // Placement mode: drop new asset at clicked globe position
        const { placementMode: pm, setPlacementMode: spm } = useStore.getState()
        if (pm) {
          const ray = viewer.camera.getPickRay(click.position)
          const globePos = viewer.scene.globe.pick(ray, viewer.scene)
          if (globePos) {
            const carto = Cesium.Cartographic.fromCartesian(globePos)
            const position = {
              lat: Cesium.Math.toDegrees(carto.latitude),
              lon: Cesium.Math.toDegrees(carto.longitude),
              alt: pm.alt ?? 0,
            }

            // Feature 21: validate terrain constraint before spawning
            const LAND_TYPES = new Set(['tank', 'missile_launcher', 'soldier_unit'])
            const targetType = pm.kind === 'target' ? pm.type : null
            const needsLand  = LAND_TYPES.has(targetType)
            const needsSea   = targetType === 'ship'
            const spawn = () => {
              if (pm.kind === 'drone') assetsApi.createDrone(pm.model, position).catch(console.error)
              else                      assetsApi.createTarget(pm.type, position).catch(console.error)
            }

            if (needsLand || needsSea) {
              const sea = likelySea(position.lon, position.lat)
              if ((needsLand && sea) || (needsSea && !sea)) {
                const where = needsLand ? 'on land' : 'in water'
                window.alert(`Cannot place ${pm.type} here — ${pm.type}s must be placed ${where}.`)
              } else {
                spawn()
              }
            } else {
              spawn()
            }
          }
          spm(null)
          return
        }

        // Normal click: select entity
        const picked = viewer.scene.pick(click.position)
        if (picked?.id) {
          const entity = picked.id
          if (entity._lattice_type === 'target') selectTarget(entity._lattice_id)
          if (entity._lattice_type === 'drone')  selectDrone(entity._lattice_id)
        }
      }, ET.LEFT_CLICK)

      // ── ESC key — cancel placement mode ─────────────────────────────────────
      const onKeyDown = (e) => {
        if (e.key === 'Escape') useStore.getState().setPlacementMode(null)
      }
      window.addEventListener('keydown', onKeyDown)
      viewer._lattice_cleanup_keydown = () => window.removeEventListener('keydown', onKeyDown)
    }

    init().catch(console.error)
    return () => {
      cancelled = true
      if (viewer) {
        if (viewer._lattice_cleanup_keydown) viewer._lattice_cleanup_keydown()
        if (!viewer.isDestroyed()) viewer.destroy()
      }
      viewerRef.current = null
      setViewerReady(false)
    }
  }, [])

  // ── Camera command handler (NLP ui_command) ─────────────────────────────────
  useEffect(() => {
    if (!cameraCommand) return
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed()) return

    const execute = async () => {
      const Cesium = (await import('cesium')).default || (await import('cesium'))
      const { ui_subtype, destination, drone_id, target_id } = cameraCommand

      const flyTo = (lon, lat, altM, durationSec = 2) => {
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(lon, lat, altM),
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-55), roll: 0 },
          duration: durationSec,
        })
      }

      if (ui_subtype === 'fly_to' && destination) {
        if (destination.altitude_km != null) {
          // NLP command with explicit altitude — fly camera to that position
          flyTo(destination.lon ?? TAIWAN_HOME.lon, destination.lat ?? TAIWAN_HOME.lat, destination.altitude_km * 1000)
        } else {
          // Panel click — center asset in the view without changing zoom or orientation
          const lon = destination.lon ?? TAIWAN_HOME.lon
          const lat = destination.lat ?? TAIWAN_HOME.lat
          viewer.camera.flyToBoundingSphere(
            new Cesium.BoundingSphere(Cesium.Cartesian3.fromDegrees(lon, lat, 0), 1000),
            {
              offset: new Cesium.HeadingPitchRange(
                viewer.camera.heading,
                viewer.camera.pitch,
                viewer.camera.positionCartographic.height,
              ),
              duration: 2,
            }
          )
        }

      } else if (ui_subtype === 'fly_to_drone') {
        // Prefer explicit destination coords (mock always provides them)
        if (destination?.lat && destination?.lon) {
          const droneAltM = (destination.altitude_km ?? 0) * 1000
          // Orbit 30 km above the drone at 45° pitch — clear tactical view
          flyTo(destination.lon, destination.lat, droneAltM + 30_000)
        } else if (drone_id) {
          // Fall back to entity position
          const entity = entityMapRef.current.drones[drone_id]
          if (entity?.position) {
            const cart = Cesium.Cartographic.fromCartesian(
              entity.position.getValue(Cesium.JulianDate.now())
            )
            flyTo(
              Cesium.Math.toDegrees(cart.longitude),
              Cesium.Math.toDegrees(cart.latitude),
              cart.height + 30_000
            )
          }
        }

      } else if (ui_subtype === 'fly_to_target') {
        if (target_id) {
          const entity = entityMapRef.current.targets[target_id]
          if (entity?.position) {
            const cart = Cesium.Cartographic.fromCartesian(
              entity.position.getValue(Cesium.JulianDate.now())
            )
            flyTo(
              Cesium.Math.toDegrees(cart.longitude),
              Cesium.Math.toDegrees(cart.latitude),
              cart.height + 20_000
            )
          }
        }

      } else if (ui_subtype === 'zoom_in') {
        const pos = viewer.camera.positionCartographic
        flyTo(
          Cesium.Math.toDegrees(pos.longitude),
          Cesium.Math.toDegrees(pos.latitude),
          Math.max(pos.height * 0.4, 5_000)
        )

      } else if (ui_subtype === 'zoom_out') {
        const pos = viewer.camera.positionCartographic
        flyTo(
          Cesium.Math.toDegrees(pos.longitude),
          Cesium.Math.toDegrees(pos.latitude),
          Math.min(pos.height * 2.5, 2_000_000)
        )

      } else if (ui_subtype === 'set_view_mode') {
        const mode = cameraCommand.view_mode
        if (mode === 'globe') flyTo(TAIWAN_HOME.lon, TAIWAN_HOME.lat, 1_500_000)
        else if (mode === 'tactical') flyTo(TAIWAN_HOME.lon, TAIWAN_HOME.lat, TAIWAN_HOME.altM)

      } else if (ui_subtype === 'toggle_layer') {
        const { layer, visible } = cameraCommand
        const show = visible !== false
        const em = entityMapRef.current
        if (layer === 'friendly' || layer === 'all') Object.values(em.drones).forEach(e => { e.show = show })
        if (layer === 'enemy' || layer === 'all') Object.values(em.targets).forEach(e => { e.show = show })
        if (layer === 'swarms') {
          const swarmDroneIds = new Set(
            useStore.getState().swarms.flatMap(s => s.drone_ids || [])
          )
          Object.entries(em.drones).forEach(([id, e]) => {
            if (swarmDroneIds.has(id)) e.show = show
          })
        }
      }
    }

    execute().catch(console.error).finally(() => setCameraCommand(null))
  }, [cameraCommand])

  // ── Update entities when battlefield state changes ─────────────────────────
  const updateEntities = useCallback(async () => {
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed()) return
    const Cesium = (await import('cesium')).default || (await import('cesium'))
    const entityMap = entityMapRef.current

    // Friendly Drones
    const currentDroneIds = new Set(drones.map(d => d.id))
    for (const id of Object.keys(entityMap.drones)) {
      if (!currentDroneIds.has(id)) {
        viewer.entities.remove(entityMap.drones[id])
        delete entityMap.drones[id]
      }
    }
    for (const drone of drones) {
      if (!drone.position) continue
      const cfg = DRONE_CONFIG[drone.model] || DRONE_CONFIG[drone.type] || DRONE_CONFIG.swarm_member
      const statusColor = STATUS_COLORS[drone.status] || [150, 150, 150]
      const color = Cesium.Color.fromBytes(...statusColor, 220)
      const pos = Cesium.Cartesian3.fromDegrees(drone.position.lon, drone.position.lat, drone.position.alt || 150)
      const isHighlighted = drone.id === selectedDroneId ||
        (selectedSwarmId !== null && drone.swarm_id === selectedSwarmId)
      const dronePixelSize  = isHighlighted ? cfg.size * 1.8 : cfg.size
      const droneOutline    = isHighlighted ? Cesium.Color.YELLOW : Cesium.Color.WHITE
      const droneOutlineW   = isHighlighted ? 3 : 1

      if (entityMap.drones[drone.id]) {
        const e = entityMap.drones[drone.id]
        e.position.setValue(pos)
        e.point.color.setValue(color)
        e.point.pixelSize.setValue(dronePixelSize)
        e.point.outlineColor.setValue(droneOutline)
        e.point.outlineWidth.setValue(droneOutlineW)
        if (e.label) e.label.text.setValue(`${cfg.label}  ${drone.name}`)
      } else {
        const e = viewer.entities.add({
          position: pos,
          point: {
            pixelSize: dronePixelSize,
            color,
            outlineColor: droneOutline,
            outlineWidth: droneOutlineW,
            heightReference: Cesium.HeightReference.NONE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: drone.type === 'recon' ? {
            text: `${cfg.label}  ${drone.name}`,
            font: '12px monospace',
            fillColor: Cesium.Color.fromBytes(...cfg.color),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -14),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          } : undefined,
        })
        e._lattice_type = 'drone'
        e._lattice_id = drone.id
        entityMap.drones[drone.id] = e
      }
    }

    // Enemy Targets
    const currentTargetIds = new Set(targets.map(t => t.id))
    for (const id of Object.keys(entityMap.targets)) {
      if (!currentTargetIds.has(id)) {
        viewer.entities.remove(entityMap.targets[id])
        delete entityMap.targets[id]
      }
    }
    for (const target of targets) {
      if (!target.position) continue
      if (target.status === 'destroyed' || target.status === 'lost') {
        if (entityMap.targets[target.id]) {
          viewer.entities.remove(entityMap.targets[target.id])
          delete entityMap.targets[target.id]
        }
        continue
      }
      const cfg = TARGET_CONFIG[target.type] || TARGET_CONFIG.drone
      const isSelected = target.id === selectedTargetId
      const alpha = Math.round(target.confidence * 220)
      const color = Cesium.Color.fromBytes(...cfg.color.slice(0, 3), alpha)
      const pos = Cesium.Cartesian3.fromDegrees(target.position.lon, target.position.lat, target.position.alt || 10)

      if (entityMap.targets[target.id]) {
        const e = entityMap.targets[target.id]
        e.position.setValue(pos)
        e.point.color.setValue(color)
        e.point.pixelSize.setValue(isSelected ? 20 : 14 * cfg.scale)
        e.point.outlineColor.setValue(isSelected ? Cesium.Color.YELLOW : Cesium.Color.fromBytes(255, 200, 0, 200))
        e.point.outlineWidth.setValue(isSelected ? 3 : 1)
      } else {
        const e = viewer.entities.add({
          position: pos,
          point: {
            pixelSize: isSelected ? 20 : 14 * cfg.scale,
            color,
            outlineColor: isSelected ? Cesium.Color.YELLOW : Cesium.Color.fromBytes(255, 200, 0, 200),
            outlineWidth: isSelected ? 3 : 1,
            heightReference: Cesium.HeightReference.NONE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: `${cfg.label}\n${Math.round(target.confidence * 100)}%`,
            font: '10px monospace',
            fillColor: Cesium.Color.fromBytes(255, 80, 80, 255),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -14),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        })
        e._lattice_type = 'target'
        e._lattice_id = target.id
        entityMap.targets[target.id] = e
      }
    }
  }, [drones, targets, selectedTargetId, selectedSwarmId, selectedDroneId])

  useEffect(() => { updateEntities() }, [updateEntities, viewerReady])

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%', height: '100%', background: '#0a0e1a',
        cursor: placementMode ? 'crosshair' : 'default',
      }}
    />
  )
}
