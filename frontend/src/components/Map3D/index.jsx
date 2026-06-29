import { useEffect, useRef, useCallback, useState } from 'react'
import { useStore } from '../../store/index.js'
import { assetsApi } from '../../services/api.js'

// Feature 18: type-specific SVG billboard icons on the 3D map.
// Each icon is a white symbol path drawn on a colored circle background.
const _ICON_PATH = {
  drone:            '<path d="M12 6 L15 11 L19 12 L15 13 L13 17 L12 15.5 L11 17 L9 13 L5 12 L9 11 Z" fill="white"/>',
  ship:             '<path d="M5 15.5 L7.5 19 L16.5 19 L19 15.5 Z" fill="white"/><rect x="10" y="7" width="5" height="10" fill="white"/><rect x="11" y="4" width="2" height="6" fill="white"/>',
  tank:             '<rect x="6" y="14" width="12" height="5" rx="1" fill="white"/><rect x="8" y="10" width="8" height="6" rx="1" fill="white"/><rect x="11.5" y="7" width="2" height="7" fill="white"/>',
  missile_launcher: '<path d="M12 4 L15.5 11 L13.5 11 L13.5 20 L10.5 20 L10.5 11 L8.5 11 Z" fill="white"/>',
  soldier_unit:     '<circle cx="12" cy="8.5" r="3" fill="white"/><path d="M9 20 L9 15 Q9 12 12 12 Q15 12 15 15 L15 20 L13.5 20 L13.5 16.5 L10.5 16.5 L10.5 20 Z" fill="white"/>',
}
const _billboardCache = {}
function _makeBillboardSVG(iconKey, bgColor, highlighted = false) {
  const cacheKey = `${iconKey}:${bgColor}:${highlighted ? 1 : 0}`
  if (_billboardCache[cacheKey]) return _billboardCache[cacheKey]
  const path = _ICON_PATH[iconKey] || _ICON_PATH.drone
  const stroke = highlighted ? 'yellow' : 'rgba(255,255,255,0.45)'
  const sw = highlighted ? 3 : 1.5
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="${bgColor}" stroke="${stroke}" stroke-width="${sw}"/>${path}</svg>`
  const uri = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)))
  _billboardCache[cacheKey] = uri
  return uri
}

// Enemy target background colors and billboard pixel sizes per type
const TARGET_BG   = { drone: '#c81e1e', ship: '#f04020', tank: '#e01010', missile_launcher: '#d0105a', soldier_unit: '#b01428' }
const TARGET_SIZE = { drone: 24, ship: 36, tank: 28, missile_launcher: 32, soldier_unit: 20 }

// Friendly drone base colors by model/type; status overrides take precedence (null = use model color)
const MODEL_BG   = { mq9_recon: '#00a8d8', scout_recon: '#2860e0', fpv_combat: '#20c020', altius_600m: '#20a840', recon: '#00a8d8', combat: '#20c020', swarm_member: '#20c020' }
const STATUS_BG  = { idle: '#4b5563', patrolling: null, searching: '#b45309', tracking: '#c2410c', engaging: '#b91c1c', returning: '#047857', offline: '#1f2937' }
const DRONE_SIZE = { mq9_recon: 28, scout_recon: 22, fpv_combat: 18, altius_600m: 20, recon: 22, combat: 18, swarm_member: 16 }

// Taiwan island-wide view
const TAIWAN_HOME = { lon: 121.0, lat: 23.8, altM: 450_000 }

// Feature 21: exact land/sea check using Natural Earth 1:10m coastline polygons.
// Polygons are served from /data/theater_land.json (generate with scripts/build_coastline.py).
// Returns null while the file is still loading — callers skip the terrain constraint in that case.

// Module-level store so data survives component remounts.
let _theaterPolygons = null   // null = not yet loaded; [] = failed/empty; [...] = ready
const _landCache = {}

function _raycastInRing(ring, lon, lat) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1]
    const xj = ring[j][0], yj = ring[j][1]
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

// Returns true (land), false (sea), or null (GeoJSON not loaded yet — caller skips constraint).
function isLand(lon, lat) {
  if (!_theaterPolygons || _theaterPolygons.length === 0) return null
  const key = `${Math.round(lon * 200)},${Math.round(lat * 200)}`
  if (key in _landCache) return _landCache[key]
  let result = false
  outer: for (const rings of _theaterPolygons) {
    if (_raycastInRing(rings[0], lon, lat)) {
      for (let h = 1; h < rings.length; h++) {
        if (_raycastInRing(rings[h], lon, lat)) continue outer
      }
      result = true
      break
    }
  }
  _landCache[key] = result
  return result
}

async function _loadTheaterLand() {
  if (_theaterPolygons !== null) return
  _theaterPolygons = []
  try {
    const resp = await fetch('/data/theater_land.json')
    if (!resp.ok) throw new Error(resp.statusText)
    const data = await resp.json()
    _theaterPolygons = data.polygons ?? []
    Object.keys(_landCache).forEach(k => delete _landCache[k])
    console.info(`[coastline] loaded ${_theaterPolygons.length} polygon(s)`)
  } catch {
    console.warn('[coastline] theater_land.json not found — terrain constraints disabled. Run: python scripts/build_coastline.py')
  }
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
      _loadTheaterLand()

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
              drag.entity.billboard.color.setValue(new Cesium.Color(1, 0.1, 0.1, 0.9))
              setTimeout(() => {
                drag.entity.billboard.color.setValue(Cesium.Color.WHITE)
              }, 800)
            }

            if (needsLand || needsSea) {
              const land = isLand(position.lon, position.lat)
              if (land !== null && ((needsLand && !land) || (needsSea && land))) revert()
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
              const land = isLand(position.lon, position.lat)
              if (land !== null && ((needsLand && !land) || (needsSea && land))) {
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

  // ── Camera command handler (panel click-to-fly: Features 19, 20) ────────────
  useEffect(() => {
    if (!cameraCommand) return
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed()) return

    const execute = async () => {
      const Cesium = (await import('cesium')).default || (await import('cesium'))
      const { destination } = cameraCommand
      if (destination) {
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
      if (drone.status === 'offline') {
        if (entityMap.drones[drone.id]) {
          viewer.entities.remove(entityMap.drones[drone.id])
          delete entityMap.drones[drone.id]
        }
        continue
      }
      const pos = Cesium.Cartesian3.fromDegrees(drone.position.lon, drone.position.lat, drone.position.alt || 150)
      const isHighlighted = drone.id === selectedDroneId ||
        (selectedSwarmId !== null && drone.swarm_id === selectedSwarmId)
      const bgColor = STATUS_BG[drone.status] ?? MODEL_BG[drone.model] ?? MODEL_BG[drone.type] ?? '#4b5563'
      const size = DRONE_SIZE[drone.model] || DRONE_SIZE[drone.type] || 16
      const svg = _makeBillboardSVG('drone', bgColor, isHighlighted)

      if (entityMap.drones[drone.id]) {
        const e = entityMap.drones[drone.id]
        e.position.setValue(pos)
        e.billboard.image.setValue(svg)
        if (e.label) e.label.text.setValue(drone.name)
      } else {
        const e = viewer.entities.add({
          position: pos,
          billboard: {
            image: svg,
            width: size,
            height: size,
            heightReference: Cesium.HeightReference.NONE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            verticalOrigin: Cesium.VerticalOrigin.CENTER,
            color: Cesium.Color.WHITE,
          },
          label: drone.type === 'recon' ? {
            text: drone.name,
            font: '11px monospace',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -(size / 2 + 3)),
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
      const pos = Cesium.Cartesian3.fromDegrees(target.position.lon, target.position.lat, target.position.alt || 10)
      const isSelected = target.id === selectedTargetId
      const bgColor = TARGET_BG[target.type] || '#c81e1e'
      const size = TARGET_SIZE[target.type] || 22
      const svg = _makeBillboardSVG(target.type, bgColor, isSelected)
      const confLabel = `${Math.round(target.confidence * 100)}%`

      if (entityMap.targets[target.id]) {
        const e = entityMap.targets[target.id]
        e.position.setValue(pos)
        e.billboard.image.setValue(svg)
        e.label.text.setValue(confLabel)
      } else {
        const e = viewer.entities.add({
          position: pos,
          billboard: {
            image: svg,
            width: size,
            height: size,
            heightReference: Cesium.HeightReference.NONE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            verticalOrigin: Cesium.VerticalOrigin.CENTER,
            color: Cesium.Color.WHITE,
          },
          label: {
            text: confLabel,
            font: '10px monospace',
            fillColor: Cesium.Color.fromCssColorString('#fca5a5'),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -(size / 2 + 2)),
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
