import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { fetchPriorityPolicy, putPriorityPolicy } from '@/api/endpoints'
import { ErrorNote } from '@/components/common/Panels'
import { Pill } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { usePendingBatch } from '@/hooks/queries'
import { plural } from '@/lib/format'
import { DIFF_HELP, DIFF_LABEL } from '@/lib/labels'

interface Props {
  open: boolean
  onClose: () => void
}

export function PolicySimulator({ open, onClose }: Props) {
  const qc = useQueryClient()
  const { data: rawPolicy } = useQuery({ queryKey: ['priority-policy'], queryFn: fetchPriorityPolicy, enabled: open })
  const { data: batch } = usePendingBatch()

  const defaultWeights = {
    waiting_time: 30,
    age_vulnerability: 20,
    journey_urgency: 25,
    additional_assistance: 15,
    disruption_impact: 10,
  }

  const policy = rawPolicy as {
    factor_weights?: Record<string, number>
    escalation?: { tier_2_max_wait_minutes?: number; enabled?: boolean }
  } | undefined

  const [weights, setWeights] = useState<Record<string, number>>(defaultWeights)
  const [waitThreshold, setWaitThreshold] = useState<number>(45)
  const [initialized, setInitialized] = useState(false)
  const [resultBatchId, setResultBatchId] = useState<string | null>(null)

  // Sync with loaded policy once
  if (policy && !initialized) {
    if (policy.factor_weights) setWeights({ ...defaultWeights, ...policy.factor_weights })
    if (policy.escalation?.tier_2_max_wait_minutes) setWaitThreshold(policy.escalation.tier_2_max_wait_minutes)
    setInitialized(true)
  }

  const weightSum = Object.values(weights).reduce((a, b) => a + Number(b || 0), 0)
  const isSumValid = Math.abs(weightSum - 100) < 0.01

  const simulate = useMutation({
    mutationFn: async () => {
      if (!rawPolicy) return
      const updated = {
        ...rawPolicy,
        factor_weights: weights,
        escalation: {
          ...((rawPolicy.escalation as Record<string, unknown>) ?? {}),
          tier_2_max_wait_minutes: Number(waitThreshold),
          enabled: true,
          escalate_to_tier: 1,
          allow_escalation_to_tier_0: false,
        },
      }
      return putPriorityPolicy(updated)
    },
    onSuccess: (res) => {
      if (res?.batch_id) setResultBatchId(res.batch_id)
    },
    onSettled: () => {
      for (const k of ['priority-policy', 'rules', 'batch', 'passengers', 'kpis', 'state']) {
        void qc.invalidateQueries({ queryKey: [k] })
      }
    },
  })

  const setPreset = (threshold: number) => {
    setWaitThreshold(threshold)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { setInitialized(false); setResultBatchId(null); onClose() } }}>
      <DialogContent className="sm:max-w-2xl text-base max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle className="text-xl font-bold">Priority Policy Simulator</DialogTitle>
            <Pill tone="info">Live Planning Sandbox</Pill>
          </div>
          <DialogDescription className="text-base text-ink-2">
            Interactively adjust scoring factor weights and wait escalation thresholds to simulate and compare recovery plan impacts.
            <b className="text-ink"> Confirmed allocations are permanently frozen</b>; only tentative and unplaced travelers are evaluated.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          {/* Factor Weights Section */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex items-baseline justify-between border-b pb-2">
              <span className="font-semibold text-base text-ink">Layer 3 Factor Weights</span>
              <span className={`font-mono text-sm font-bold ${isSumValid ? 'text-confirmed-ink' : 'text-unresolved-ink'}`}>
                Sum: {weightSum}% {isSumValid ? '✓' : '(Must equal 100%)'}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {[
                { key: 'waiting_time', label: 'Waiting Time / Delay' },
                { key: 'age_vulnerability', label: 'Age Vulnerability' },
                { key: 'journey_urgency', label: 'Journey Urgency (Deadline)' },
                { key: 'additional_assistance', label: 'Additional Assistance' },
                { key: 'disruption_impact', label: 'Disruption Impact' },
              ].map(({ key, label }) => (
                <div key={key} className="flex items-center justify-between gap-2 p-1.5 rounded bg-secondary/20">
                  <span className="text-sm text-ink-2 font-medium">{label}</span>
                  <div className="flex items-center gap-1">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={weights[key] ?? 0}
                      onChange={(e) => setWeights({ ...weights, [key]: Number(e.target.value) })}
                      className="h-8 w-16 text-right font-mono text-sm"
                    />
                    <span className="text-xs text-ink-2">%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Wait Escalation Threshold Section */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex items-baseline justify-between border-b pb-2">
              <span className="font-semibold text-base text-ink">Starvation Prevention: Wait Escalation</span>
              <span className="font-mono text-sm text-amber-800 dark:text-amber-300 font-semibold">
                Promote Tier 2 → Tier 1 at {waitThreshold}m
              </span>
            </div>

            <div className="space-y-2">
              <label className="text-sm text-ink-2">
                Passengers waiting beyond this threshold are escalated to Tier 1 (never Tier 0):
              </label>
              <div className="flex items-center gap-3">
                <Input
                  type="range"
                  min={15}
                  max={180}
                  step={5}
                  value={waitThreshold}
                  onChange={(e) => setWaitThreshold(Number(e.target.value))}
                  className="flex-1 cursor-pointer"
                />
                <span className="font-mono font-bold text-base w-16 text-right">{waitThreshold} min</span>
              </div>

              {/* Presets */}
              <div className="flex flex-wrap gap-2 pt-1 text-xs">
                <span className="text-ink-2 self-center font-medium">Quick Presets:</span>
                <button
                  type="button"
                  className={`px-2.5 py-1 rounded border font-mono transition ${waitThreshold === 30 ? 'bg-navy text-white' : 'bg-secondary hover:bg-page'}`}
                  onClick={() => setPreset(30)}
                >
                  30m (Demo Fast Escalation)
                </button>
                <button
                  type="button"
                  className={`px-2.5 py-1 rounded border font-mono transition ${waitThreshold === 45 ? 'bg-navy text-white' : 'bg-secondary hover:bg-page'}`}
                  onClick={() => setPreset(45)}
                >
                  45m (Standard Demo)
                </button>
                <button
                  type="button"
                  className={`px-2.5 py-1 rounded border font-mono transition ${waitThreshold === 120 ? 'bg-navy text-white' : 'bg-secondary hover:bg-page'}`}
                  onClick={() => setPreset(120)}
                >
                  120m (Production)
                </button>
              </div>
            </div>
          </div>

          {/* Simulation Result Comparison (Diff) */}
          {batch && (
            <div className="rounded-lg border border-tentative/40 bg-tentative/5 p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-tentative-ink uppercase tracking-wide">
                  Simulation Outcome: Batch {batch.batch_id}
                </span>
                <span className="text-xs font-mono text-ink-2">Cause: {batch.cause}{resultBatchId && ` · Proposed: ${resultBatchId}`}</span>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5 text-center text-xs">
                {(['NEWLY_PLACED', 'RESHUFFLED', 'PLACED', 'DISPLACED', 'UNRESOLVED'] as const).map((c) => (
                  <div key={c} className="rounded bg-card p-2 border">
                    <div className="text-ink-2 font-medium">{DIFF_LABEL[c]}</div>
                    <div className="font-mono text-lg font-bold text-ink">{batch.diff[c]?.heads ?? 0}</div>
                    <div className="text-[11px] text-ink-2">{plural(batch.diff[c]?.groups ?? 0, 'grp')}</div>
                  </div>
                ))}
              </div>
              <p className="text-xs text-ink-2 italic pt-1">
                {DIFF_HELP.NEWLY_PLACED}: accommodated under this policy. Confirmed allocations were not touched.
              </p>
            </div>
          )}

          <ErrorNote error={simulate.error} />
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" size="lg" onClick={onClose}>
            Close
          </Button>
          <Button
            size="lg"
            className="font-semibold"
            disabled={!isSumValid || simulate.isPending}
            onClick={() => simulate.mutate()}
          >
            {simulate.isPending ? 'Simulating…' : 'Simulate & Propose Plan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
