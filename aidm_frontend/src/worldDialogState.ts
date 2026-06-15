import type { World } from './types'

export type WorldFormState = {
  mode: 'create' | 'edit'
  worldId: number | null
  name: string
  description: string
  error: string
  pending: boolean
}

export type WorldDeleteDialogState = {
  world: World
  error: string
  pending: boolean
  canForce: boolean
} | null

export const emptyWorldForm: WorldFormState = {
  mode: 'create',
  worldId: null,
  name: '',
  description: '',
  error: '',
  pending: false,
}
