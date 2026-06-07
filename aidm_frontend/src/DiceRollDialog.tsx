import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import {
  AmbientLight,
  BoxGeometry,
  BufferGeometry,
  CanvasTexture,
  DirectionalLight,
  DodecahedronGeometry,
  DoubleSide,
  EdgesGeometry,
  Float32BufferAttribute,
  Group,
  IcosahedronGeometry,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  OctahedronGeometry,
  PerspectiveCamera,
  PlaneGeometry,
  Scene,
  SRGBColorSpace,
  TetrahedronGeometry,
  Vector3,
  WebGLRenderer,
  type Material,
  type Object3D,
  type Texture,
} from 'three'

type DiceRollStatus = 'rolling' | 'sending'

type DiceRollDialogProps = {
  die: string
  result: number
  targetLabel?: string | null
  rollKey: number
  status: DiceRollStatus
  onCancel: () => void
  onComplete: () => void
}

const ROLL_DURATION_MS = 2600
const RESULT_HOLD_MS = 1250
const FACE_LABEL_DEPTH_OFFSET = 0.045
const FRONT_NORMAL = new Vector3(0, 0, 1)

const DIE_SIDES: Record<string, number> = {
  d4: 4,
  d6: 6,
  d8: 8,
  d10: 10,
  d12: 12,
  d20: 20,
  d100: 100,
}

type FaceSample = {
  center: Vector3
  normal: Vector3
}

function createBipyramidGeometry(points: number) {
  const radius = 1.08
  const height = 1.32
  const vertices: number[] = []
  const ring = Array.from({ length: points }, (_, index) => {
    const angle = (index / points) * Math.PI * 2 + Math.PI / points
    return new Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius)
  })
  const top = new Vector3(0, height, 0)
  const bottom = new Vector3(0, -height, 0)

  for (let index = 0; index < points; index += 1) {
    const nextIndex = (index + 1) % points
    vertices.push(top.x, top.y, top.z, ring[index].x, ring[index].y, ring[index].z, ring[nextIndex].x, ring[nextIndex].y, ring[nextIndex].z)
    vertices.push(
      bottom.x,
      bottom.y,
      bottom.z,
      ring[nextIndex].x,
      ring[nextIndex].y,
      ring[nextIndex].z,
      ring[index].x,
      ring[index].y,
      ring[index].z,
    )
  }

  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3))
  geometry.computeVertexNormals()
  return geometry
}

function createGeometryForDie(die: string) {
  const normalized = die.toLowerCase()
  if (normalized === 'd4') return new TetrahedronGeometry(1.35)
  if (normalized === 'd6') return new BoxGeometry(1.72, 1.72, 1.72)
  if (normalized === 'd8') return new OctahedronGeometry(1.42)
  if (normalized === 'd10') return createBipyramidGeometry(5)
  if (normalized === 'd12') return new DodecahedronGeometry(1.34)
  if (normalized === 'd100') return createBipyramidGeometry(10)
  return new IcosahedronGeometry(1.38)
}

function getDieSides(die: string) {
  return DIE_SIDES[die.toLowerCase()] ?? 20
}

function createCubeFaceSamples(): FaceSample[] {
  const offset = 0.88
  return [
    { center: new Vector3(0, 0, offset), normal: new Vector3(0, 0, 1) },
    { center: new Vector3(offset, 0, 0), normal: new Vector3(1, 0, 0) },
    { center: new Vector3(-offset, 0, 0), normal: new Vector3(-1, 0, 0) },
    { center: new Vector3(0, offset, 0), normal: new Vector3(0, 1, 0) },
    { center: new Vector3(0, -offset, 0), normal: new Vector3(0, -1, 0) },
    { center: new Vector3(0, 0, -offset), normal: new Vector3(0, 0, -1) },
  ]
}

function createGeometryFaceSamples(geometry: BufferGeometry): FaceSample[] {
  const source = geometry.index ? geometry.toNonIndexed() : geometry
  const position = source.getAttribute('position')
  const samples: FaceSample[] = []

  for (let index = 0; index < position.count; index += 3) {
    const a = new Vector3().fromBufferAttribute(position, index)
    const b = new Vector3().fromBufferAttribute(position, index + 1)
    const c = new Vector3().fromBufferAttribute(position, index + 2)
    const normal = new Vector3().subVectors(b, a).cross(new Vector3().subVectors(c, a)).normalize()
    if (!Number.isFinite(normal.lengthSq()) || normal.lengthSq() === 0) continue
    const center = new Vector3().addVectors(a, b).add(c).multiplyScalar(1 / 3)
    samples.push({ center, normal })
  }

  if (source !== geometry) {
    source.dispose()
  }
  return samples
}

function createFaceSamples(die: string, geometry: BufferGeometry) {
  return die.toLowerCase() === 'd6' ? createCubeFaceSamples() : createGeometryFaceSamples(geometry)
}

function pickEvenly<T>(items: T[], count: number) {
  if (count >= items.length) return items
  return Array.from({ length: count }, (_, index) => {
    const itemIndex = Math.floor((index / count) * items.length)
    return items[itemIndex]
  })
}

function sideLabelValues(die: string, result: number, count: number) {
  const sides = getDieSides(die)
  const pool = Array.from({ length: sides }, (_, index) => index + 1).filter((value) => value !== result)
  const start = Math.abs(result + count) % Math.max(pool.length, 1)
  return Array.from({ length: count }, (_, index) => pool[(start + index * 3) % pool.length] ?? index + 1)
}

function createFaceLabelTexture(label: string, isResult = false) {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 256
  const context = canvas.getContext('2d')
  if (context) {
    context.clearRect(0, 0, canvas.width, canvas.height)
    const center = canvas.width / 2
    const badgeRadius = isResult ? 88 : 72
    const fontSize = label.length >= 3 ? (isResult ? 80 : 56) : label.length === 2 ? (isResult ? 98 : 68) : isResult ? 120 : 82

    context.fillStyle = isResult ? 'rgba(8, 16, 16, 0.88)' : 'rgba(8, 16, 16, 0.68)'
    context.strokeStyle = isResult ? 'rgba(255, 218, 166, 0.92)' : 'rgba(255, 218, 166, 0.72)'
    context.lineWidth = isResult ? 9 : 6
    context.beginPath()
    context.arc(center, center, badgeRadius, 0, Math.PI * 2)
    context.fill()
    context.stroke()
    context.shadowColor = 'rgba(0, 0, 0, 0.58)'
    context.shadowBlur = 8
    context.shadowOffsetY = 3
    context.fillStyle = '#fff3df'
    context.font = `800 ${fontSize}px Inter, system-ui, sans-serif`
    context.textAlign = 'center'
    context.textBaseline = 'middle'
    context.fillText(label, center, center + (label.length >= 3 ? 3 : 2))
  }

  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  return texture
}

function createNumberPlane(label: string, sample: FaceSample, isResult = false) {
  const labelScale = isResult ? (label.length >= 3 ? 0.94 : 0.78) : label.length >= 3 ? 0.54 : 0.46
  const texture = createFaceLabelTexture(label, isResult)
  const material = new MeshBasicMaterial({
    map: texture,
    transparent: true,
    side: DoubleSide,
    depthWrite: false,
  })
  const plane = new Mesh(new PlaneGeometry(labelScale, labelScale), material)
  plane.position.copy(sample.center).addScaledVector(sample.normal, FACE_LABEL_DEPTH_OFFSET)
  plane.quaternion.setFromUnitVectors(FRONT_NORMAL, sample.normal)
  return plane
}

function disposeMaterial(material: Material) {
  const mapped = material as Material & { map?: Texture }
  mapped.map?.dispose()
  material.dispose()
}

function disposeObject(object: Object3D) {
  object.traverse((child) => {
    const mesh = child as Mesh
    mesh.geometry?.dispose()
    const material = mesh.material
    if (Array.isArray(material)) {
      material.forEach(disposeMaterial)
    } else if (material) {
      disposeMaterial(material)
    }
  })
}

function createDiceGroup(die: string, result: number) {
  const normalizedDie = die.toLowerCase()
  const geometry = createGeometryForDie(die)
  const faceSamples = createFaceSamples(normalizedDie, geometry)
  const frontFace = faceSamples.reduce((best, sample) => (sample.normal.z > best.normal.z ? sample : best), faceSamples[0])
  const sideFaces = faceSamples.filter((sample) => sample !== frontFace && sample.normal.dot(frontFace.normal) < 0.96)
  const sideLabels = pickEvenly(sideFaces, Math.min(getDieSides(normalizedDie) - 1, 22, sideFaces.length))
  const sideValues = sideLabelValues(normalizedDie, result, sideLabels.length)
  const group = new Group()
  const mesh = new Mesh(
    geometry,
    new MeshStandardMaterial({
      color: 0xc64f22,
      emissive: 0x2a0d04,
      metalness: 0.18,
      roughness: 0.54,
      flatShading: true,
    }),
  )
  const edgeMaterial = new LineBasicMaterial({
    color: 0xffd19a,
    transparent: true,
    opacity: 0.64,
  })
  const edges = new LineSegments(new EdgesGeometry(geometry), edgeMaterial)
  const resultFace = createNumberPlane(String(result), frontFace, true)
  resultFace.visible = false

  mesh.castShadow = true
  mesh.receiveShadow = true
  group.add(mesh, edges)
  sideLabels.forEach((sample, index) => {
    group.add(createNumberPlane(String(sideValues[index]), sample))
  })
  group.add(resultFace)
  return { group, resultFace }
}

function DiceCanvas({
  die,
  result,
  rollKey,
  onLanded,
  onComplete,
}: {
  die: string
  result: number
  rollKey: number
  onLanded: () => void
  onComplete: () => void
}) {
  const mountRef = useRef<HTMLDivElement | null>(null)
  const completeRef = useRef(onComplete)
  const landedRef = useRef(onLanded)

  useEffect(() => {
    completeRef.current = onComplete
  }, [onComplete])

  useEffect(() => {
    landedRef.current = onLanded
  }, [onLanded])

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return undefined

    const renderer = new WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.shadowMap.enabled = true
    renderer.outputColorSpace = SRGBColorSpace
    renderer.domElement.setAttribute('aria-hidden', 'true')
    mount.appendChild(renderer.domElement)

    const scene = new Scene()
    const camera = new PerspectiveCamera(38, 1, 0.1, 100)
    camera.position.set(0, 0.35, 5.6)

    const keyLight = new DirectionalLight(0xffdfbd, 2.5)
    keyLight.position.set(3.2, 4.4, 4.2)
    const rimLight = new DirectionalLight(0x72b59b, 1.15)
    rimLight.position.set(-4, 1.2, -2.4)
    scene.add(new AmbientLight(0xffffff, 0.58), keyLight, rimLight)

    const { group: dice, resultFace } = createDiceGroup(die, result)
    dice.rotation.set(-0.55, 0.55, 0.22)
    scene.add(dice)

    let frameId = 0
    let completionTimer = 0
    let completed = false

    const render = () => renderer.render(scene, camera)
    const resize = () => {
      const width = Math.max(240, mount.clientWidth)
      const height = Math.max(220, mount.clientHeight)
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      render()
    }
    const observer =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => resize())
        : null
    observer?.observe(mount)
    window.addEventListener('resize', resize)
    resize()

    const startedAt = performance.now()
    const spinSeed = rollKey % 17
    const finalX = -0.16 + (spinSeed % 5) * 0.018
    const finalY = 0.26 + (result % 7) * 0.012
    const finalZ = 0.06 + (spinSeed % 3) * 0.012

    const animate = (time: number) => {
      const rawProgress = Math.min((time - startedAt) / ROLL_DURATION_MS, 1)
      const eased = 1 - (1 - rawProgress) ** 3
      const suspenseProgress = rawProgress > 0.72 ? (rawProgress - 0.72) / 0.28 : 0
      const settleWeight = 1 - suspenseProgress
      const bounce = Math.sin(rawProgress * Math.PI * 8.5) * (1 - eased) * 0.34
      const wobble = Math.sin(rawProgress * Math.PI * 11) * Math.max(0, settleWeight) * 0.08

      dice.rotation.x = finalX + (1 - eased) * (Math.PI * 10.6 + spinSeed * 0.24) + wobble
      dice.rotation.y = finalY + (1 - eased) * (Math.PI * 11.4 + result * 0.045) - wobble * 0.6
      dice.rotation.z = finalZ + (1 - eased) * Math.PI * 7.2 + wobble * 0.4
      dice.position.y = bounce
      dice.scale.setScalar(0.88 + Math.sin(rawProgress * Math.PI) * 0.07)
      render()

      if (rawProgress < 1) {
        frameId = window.requestAnimationFrame(animate)
        return
      }
      if (!completed) {
        completed = true
        resultFace.visible = true
        render()
        landedRef.current()
        completionTimer = window.setTimeout(() => completeRef.current(), RESULT_HOLD_MS)
      }
    }

    frameId = window.requestAnimationFrame(animate)

    return () => {
      window.cancelAnimationFrame(frameId)
      window.clearTimeout(completionTimer)
      window.removeEventListener('resize', resize)
      observer?.disconnect()
      disposeObject(scene)
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [die, result, rollKey])

  return <div ref={mountRef} className="dice-canvas" data-testid="dice-roller-canvas" />
}

export default function DiceRollDialog({
  die,
  result,
  targetLabel,
  rollKey,
  status,
  onCancel,
  onComplete,
}: DiceRollDialogProps) {
  const [landedRollKey, setLandedRollKey] = useState<number | null>(null)
  const hasLanded = landedRollKey === rollKey
  const isSending = status === 'sending'
  const title = isSending ? 'Sending roll' : hasLanded ? 'Landed' : 'Rolling dice'
  const statusText = isSending
    ? 'Sending to chat...'
    : hasLanded
      ? 'Landed. Sending roll...'
      : 'Still tumbling...'

  return (
    <section
      className={`dice-dialog ${status}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="dice-roll-title"
    >
      <header>
        <div>
          <span>{die.toUpperCase()} roll</span>
          <h2 id="dice-roll-title">{title}</h2>
        </div>
        <button type="button" aria-label="Close dice roller" onClick={onCancel} disabled={isSending}>
          <X size={18} />
        </button>
      </header>
      <div className="dice-stage">
        <DiceCanvas
          die={die}
          result={result}
          rollKey={rollKey}
          onLanded={() => setLandedRollKey(rollKey)}
          onComplete={onComplete}
        />
        <div className="dice-readout" aria-live="polite">
          <span>{die.toUpperCase()}</span>
          <strong>{hasLanded || isSending ? result : '...'}</strong>
          <small>{statusText}</small>
          {targetLabel ? <small>Target: {targetLabel}</small> : null}
        </div>
      </div>
    </section>
  )
}
