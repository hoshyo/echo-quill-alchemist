import { useEffect, useRef } from 'react'
import { useAlchemist, type Candidate } from './store'
import './App.css'

export default function App() {
  const connect = useAlchemist((s) => s.connect)
  useEffect(() => {
    connect()
  }, [connect])

  return (
    <div className="app">
      <Header />
      <main className="grid">
        <RulesPanel />
        <ArenaPanel />
        <LogsPanel />
      </main>
    </div>
  )
}

function Header() {
  const connected = useAlchemist((s) => s.connected)
  const phase = useAlchemist((s) => s.phase)
  const chunks = useAlchemist((s) => s.chunks_processed)
  const dpoCount = useAlchemist((s) => s.dpo_pairs.length)
  return (
    <header className="header">
      <h1>Echo-Quill Dashboard</h1>
      <div className="stats">
        <span className={`pill ${connected ? 'ok' : 'bad'}`}>
          {connected ? '● ws connected' : '○ ws down'}
        </span>
        <span className="pill">
          phase: <b>{phase}</b>
        </span>
        <span className="pill">
          chunks: <b>{chunks}</b>
        </span>
        <span className="pill">
          DPO pairs: <b>{dpoCount}</b>
        </span>
      </div>
    </header>
  )
}

function RulesPanel() {
  const rules = useAlchemist((s) => s.rules)
  return (
    <section className="panel">
      <h2>
        Style Rules <span className="muted">({rules.length})</span>
      </h2>
      <div className="scroll">
        {rules.length === 0 && (
          <div className="empty">尚未提取规则。等待第一个 chunk 入炉…</div>
        )}
        {rules.map((r) => {
          const pct = Math.max(
            0,
            Math.min(100, (r.lifespan / Math.max(1, r.initial_lifespan)) * 100),
          )
          const heat = Math.min(1, r.hit_count / 10)
          return (
            <div key={r.id} className="rule">
              <div className="rule-row">
                <span className="rule-desc" title={r.description}>
                  {r.description}
                </span>
                <span
                  className="rule-hits"
                  style={{
                    background: `rgba(255,140,40,${0.15 + heat * 0.6})`,
                  }}
                >
                  hit {r.hit_count}
                </span>
              </div>
              <div className="bar">
                <div className="bar-fill" style={{ width: `${pct}%` }} />
              </div>
              <div className="bar-meta">
                <span className="muted">
                  life {r.lifespan}/{r.initial_lifespan}
                </span>
                <span className="muted small">
                  {r.last_hit_at
                    ? `last hit ${new Date(r.last_hit_at).toLocaleTimeString()}`
                    : 'never hit'}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function ArenaPanel() {
  const candidates = useAlchemist((s) => s.arena_candidates)
  const hardNeg = useAlchemist((s) => s.arena_hard_negative)
  const ctx = useAlchemist((s) => s.last_context_preview)
  return (
    <section className="panel">
      <h2>
        Arena{' '}
        <span className="muted">
          Best-of-{Math.max(candidates.length, 1)} + Hard Negative
        </span>
      </h2>
      <div className="ctx">
        <div className="muted small">上文 (尾部 200 字)</div>
        <pre>{ctx || '—'}</pre>
      </div>
      <div className="cands scroll">
        {candidates.length === 0 && !hardNeg && (
          <div className="empty">竞技场空。等待生成…</div>
        )}
        {candidates.map((c, i) => (
          <CandidateCard key={`n${i}`} c={c} rank={i + 1} />
        ))}
        {hardNeg && <CandidateCard c={hardNeg} rank={0} />}
      </div>
    </section>
  )
}

function CandidateCard({ c, rank }: { c: Candidate; rank: number }) {
  const isNeg = c.is_hard_negative || rank === 0
  const cls = isNeg ? 'cand neg' : rank === 1 ? 'cand best' : 'cand'
  return (
    <div className={cls}>
      <div className="cand-head">
        <span className="cand-rank">{isNeg ? 'HARD NEG' : `#${rank}`}</span>
        <span className="cand-scores">
          sem <b>{c.semantic_score.toFixed(3)}</b> · rouge{' '}
          <b>{c.rouge_score.toFixed(3)}</b> · ∑{' '}
          <b>{c.composite_score.toFixed(3)}</b>
        </span>
      </div>
      <pre className="cand-text">{c.text}</pre>
    </div>
  )
}

function LogsPanel() {
  const logs = useAlchemist((s) => s.logs)
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [logs.length])
  return (
    <section className="panel">
      <h2>
        Logs <span className="muted">({logs.length})</span>
      </h2>
      <div ref={ref} className="logs scroll">
        {logs.length === 0 && <div className="empty">日志流静默中…</div>}
        {logs.map((l, i) => (
          <div key={i} className="logline">
            <span className="ts">{new Date(l.ts).toLocaleTimeString()}</span>
            <span className="ln">{l.line}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
