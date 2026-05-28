import { create } from 'zustand'

// ---------- Wire types (mirror backend/models.py) ----------

export type StyleRule = {
  id: string
  description: string
  lifespan: number
  initial_lifespan: number
  hit_count: number
  born_at: string
  last_hit_at: string | null
}

export type Candidate = {
  text: string
  semantic_score: number
  rouge_score: number
  composite_score: number
  is_hard_negative: boolean
}

export type DPOPair = {
  id: string
  prompt: string
  chosen: string
  rejected: string
  chosen_score: number
  rejected_score: number
  margin: number
  reason: string
  created_at: string
}

export type LogLine = { ts: string; line: string }

// ---------- Store ----------

type State = {
  connected: boolean
  phase: string
  chunks_processed: number
  rules: StyleRule[]
  arena_candidates: Candidate[]
  arena_hard_negative: Candidate | null
  dpo_pairs: DPOPair[]
  logs: LogLine[]
  last_context_preview: string
  last_truth_preview: string
}

type Actions = {
  connect: (url?: string) => void
}

const WS_URL =
  (import.meta as any).env?.VITE_WS_URL ?? 'ws://localhost:8000/ws/alchemist'

const MAX_LOGS = 500
const MAX_DPO = 200

export const useAlchemist = create<State & Actions>((set, get) => ({
  connected: false,
  phase: 'idle',
  chunks_processed: 0,
  rules: [],
  arena_candidates: [],
  arena_hard_negative: null,
  dpo_pairs: [],
  logs: [],
  last_context_preview: '',
  last_truth_preview: '',
  connect: (url = WS_URL) => {
    let retries = 0
    const open = () => {
      const ws = new WebSocket(url)
      ws.onopen = () => {
        retries = 0
        set({ connected: true })
      }
      ws.onclose = () => {
        set({ connected: false })
        retries += 1
        const wait = Math.min(1000 * 2 ** retries, 15000)
        setTimeout(open, wait)
      }
      ws.onerror = () => {
        try {
          ws.close()
        } catch {
          // ignore
        }
      }
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)
          handle(m, set, get)
        } catch (e) {
          console.error('bad ws message', e)
        }
      }
    }
    open()
  },
}))

// ---------- Reducer ----------

function pushLog(s: State, line: string, ts: string): LogLine[] {
  const next = [...s.logs, { ts, line }]
  if (next.length > MAX_LOGS) next.splice(0, next.length - MAX_LOGS)
  return next
}

function handle(
  m: { type: string; payload: any; ts?: string },
  set: (partial: Partial<State> | ((s: State) => Partial<State>)) => void,
  _get: () => State,
) {
  const ts = m.ts ?? new Date().toISOString()
  switch (m.type) {
    case 'snapshot': {
      const p = m.payload || {}
      set({
        rules: p.rules ?? [],
        arena_candidates: p.arena_candidates ?? [],
        arena_hard_negative: p.arena_hard_negative ?? null,
        dpo_pairs: (p.dpo_pairs ?? []).slice(-MAX_DPO),
        logs: (p.logs ?? [])
          .map((line: string) => ({ ts, line }))
          .slice(-MAX_LOGS),
        chunks_processed: p.chunks_processed ?? 0,
        phase: p.current_phase ?? 'idle',
        last_context_preview: p.last_context_preview ?? '',
        last_truth_preview: p.last_truth_preview ?? '',
      })
      break
    }
    case 'log':
      set((s) => ({ logs: pushLog(s, m.payload?.line ?? '', ts) }))
      break
    case 'phase':
      set({ phase: m.payload?.phase ?? 'idle' })
      break
    case 'rules':
      set({ rules: m.payload ?? [] })
      break
    case 'arena':
      set({
        arena_candidates: m.payload?.candidates ?? [],
        arena_hard_negative: m.payload?.hard_negative ?? null,
      })
      break
    case 'dpo':
      set((s) => {
        const next = [...s.dpo_pairs, m.payload]
        if (next.length > MAX_DPO) next.splice(0, next.length - MAX_DPO)
        return { dpo_pairs: next }
      })
      break
    case 'chunk_start':
      set({ last_context_preview: m.payload?.context_preview ?? '' })
      break
    case 'chunk_done':
      set((s) => ({
        chunks_processed: m.payload?.chunk_index ?? s.chunks_processed,
      }))
      break
  }
}
