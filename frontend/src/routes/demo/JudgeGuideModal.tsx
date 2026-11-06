import { useState } from 'react'
import { Pill, TierChip } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { fmtPoints } from '@/lib/labels'

interface Props {
  open: boolean
  onClose: () => void
}

type TabKey = 'architecture' | 'formula' | 'groups_escalation' | 'database_safety' | 'pitch_script'

export function JudgeGuideModal({ open, onClose }: Props) {
  const [tab, setTab] = useState<TabKey>('architecture')

  // Interactive calculator state initialized with the user's exact example
  const [waitingTime, setWaitingTime] = useState<number>(80)
  const [ageScore, setAgeScore] = useState<number>(70)
  const [urgencyScore, setUrgencyScore] = useState<number>(100)
  const [assistanceScore, setAssistanceScore] = useState<number>(60)
  const [impactScore, setImpactScore] = useState<number>(90)
  const [waitingMinutes, setWaitingMinutes] = useState<number>(90)

  // Calculations
  const waitingPts = (waitingTime * 30) / 100
  const agePts = (ageScore * 20) / 100
  const urgencyPts = (urgencyScore * 25) / 100
  const assistancePts = (assistanceScore * 15) / 100
  const impactPts = (impactScore * 10) / 100
  const baseScore = waitingPts + agePts + urgencyPts + assistancePts + impactPts
  const ageingPts = waitingMinutes * 0.1
  const effectiveScore = baseScore + ageingPts

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-4xl max-h-[90vh] overflow-y-auto text-base">
        <DialogHeader>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
            <div>
              <div className="flex items-center gap-2">
                <DialogTitle className="text-2xl font-bold">SafarSet Prioritisation Architecture</DialogTitle>
                <Pill tone="info">Judge Presentation Guide</Pill>
              </div>
              <DialogDescription className="text-sm text-ink-2 mt-0.5">
                4-layer hybrid prioritisation, starvation prevention, atomic capacity safety &amp; explainability.
              </DialogDescription>
            </div>
            <div className="flex items-center gap-1.5 font-mono text-xs">
              <span className="size-2 rounded-full bg-confirmed" />
              <span>Full System Overview</span>
            </div>
          </div>
        </DialogHeader>

        {/* Tab Navigation */}
        <div className="flex flex-wrap gap-1 border-b border-line pb-2 text-sm font-semibold">
          {[
            { key: 'architecture', label: '1. Architecture & Layers' },
            { key: 'formula', label: '2. Scoring Formula & Calculator' },
            { key: 'groups_escalation', label: '3. Group Logic & Escalation' },
            { key: 'database_safety', label: '4. Concurrency & DB Safety' },
            { key: 'pitch_script', label: '5. Judge Presentation Script' },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key as TabKey)}
              className={`rounded-lg px-3 py-1.5 transition ${
                tab === key
                  ? 'bg-navy text-white shadow-sm'
                  : 'text-ink-2 hover:bg-secondary hover:text-ink'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Tab 1: 4-Layer Architecture */}
        {tab === 'architecture' && (
          <div className="space-y-5 py-2">
            <div>
              <h3 className="text-lg font-bold text-ink">4-Layer Hybrid Prioritisation Overview</h3>
              <p className="text-sm text-ink-2 mt-1">
                During transport disruptions, passenger demand far exceeds available capacity. Rather than a naive first-come-first-served queue or a single opaque score, SafarSet cleanly separates feasibility, policy tiers, soft weighting, and group integrity.
              </p>
            </div>

            {/* Architecture Cards */}
            <div className="grid gap-3.5 sm:grid-cols-2">
              {/* Layer 1 */}
              <div className="rounded-xl border border-line bg-card p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-navy">Layer 1</span>
                  <Pill tone="bad">Hard Feasibility</Pill>
                </div>
                <h4 className="font-bold text-base text-ink">Hard Constraints</h4>
                <p className="text-sm text-ink-2">
                  Feasibility is strictly decoupled from fairness. A passenger group must satisfy all hard constraints before scoring is ever considered:
                </p>
                <ul className="text-xs space-y-1 text-ink list-disc list-inside">
                  <li><b>Route compatibility</b>: Vehicle serves passenger destination</li>
                  <li><b>Segment capacity</b>: Seats exist on <i>every</i> journey segment</li>
                  <li><b>Mandatory accessibility</b>: Wheelchair-accessible vehicle</li>
                  <li><b>Group integrity</b>: Groups cannot be split across vehicles</li>
                  <li><b>Feasibility deadlines</b>: Arrival within hard deadlines</li>
                </ul>
                <div className="rounded bg-secondary/50 p-2 text-xs italic text-ink-2 border-l-2 border-navy">
                  &ldquo;A high priority score never overrides vehicle suitability or capacity.&rdquo;
                </div>
              </div>

              {/* Layer 2 */}
              <div className="rounded-xl border border-line bg-card p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-navy">Layer 2</span>
                  <Pill tone="warn">Hierarchical Tiers</Pill>
                </div>
                <h4 className="font-bold text-base text-ink">Priority Tiers</h4>
                <p className="text-sm text-ink-2">
                  Passengers are categorized into operational tiers. Higher tiers are allocated strictly before lower tiers:
                </p>
                <div className="space-y-1.5 text-xs">
                  <div className="flex items-center gap-2 p-1.5 rounded bg-red-500/10 border border-red-500/20">
                    <TierChip tier={0} name="Tier 0 · Critical" />
                    <span className="text-ink">Verified medical emergencies &amp; critical cases</span>
                  </div>
                  <div className="flex items-center gap-2 p-1.5 rounded bg-amber-500/10 border border-amber-500/20">
                    <TierChip tier={1} name="Tier 1 · High" />
                    <span className="text-ink">Disability, wheelchair, elderly needing help, unaccompanied minors</span>
                  </div>
                  <div className="flex items-center gap-2 p-1.5 rounded bg-slate-500/10 border border-slate-400/20">
                    <TierChip tier={2} name="Tier 2 · Standard" />
                    <span className="text-ink">All other eligible passengers (ranked by score &amp; wait)</span>
                  </div>
                </div>
                <p className="text-xs text-ink-2">
                  *A senior citizen without assistance needs is Tier 2 (age is a soft factor, avoiding age discrimination).
                </p>
              </div>

              {/* Layer 3 */}
              <div className="rounded-xl border border-line bg-card p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-navy">Layer 3</span>
                  <Pill tone="info">Weighted Ranking</Pill>
                </div>
                <h4 className="font-bold text-base text-ink">Weighted Scoring Within Tiers</h4>
                <p className="text-sm text-ink-2">
                  Within the same tier, groups are ranked by 5 normalized factors ($0–100$) plus linear uncapped ageing:
                </p>
                <div className="grid grid-cols-2 gap-1 text-xs font-mono">
                  <div className="p-1 rounded bg-secondary">Waiting time: 30%</div>
                  <div className="p-1 rounded bg-secondary">Age vulnerability: 20%</div>
                  <div className="p-1 rounded bg-secondary">Journey urgency: 25%</div>
                  <div className="p-1 rounded bg-secondary">Additional assistance: 15%</div>
                  <div className="col-span-2 p-1 rounded bg-secondary">Disruption impact: 10%</div>
                </div>
                <p className="text-xs text-ink-2">
                  + Waiting-time ageing (0.1 points/min = 6 points/hr) guarantees queue progress.
                </p>
              </div>

              {/* Layer 4 */}
              <div className="rounded-xl border border-line bg-card p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-navy">Layer 4</span>
                  <Pill tone="neutral">Group Policy</Pill>
                </div>
                <h4 className="font-bold text-base text-ink">Group Prioritisation</h4>
                <p className="text-sm text-ink-2">
                  Passengers travel in families and parties. Groups are never split across vehicles:
                </p>
                <ul className="text-xs space-y-1 text-ink list-disc list-inside">
                  <li><b>Group Tier</b>: Highest-priority member tier ($\min(T_1, T_2, \dots)$)</li>
                  <li><b>Group Score</b>: Average score of members in that highest tier</li>
                  <li><b>Anti-Abuse Verification</b>: Groups $&gt; 4$ require operator companion verification to inherit Tier 0 or 1.</li>
                </ul>
                <div className="rounded bg-secondary/50 p-2 text-xs italic text-ink-2 border-l-2 border-navy">
                  &ldquo;A wheelchair user keeps their family together, but artificial mega-groups cannot exploit priority.&rdquo;
                </div>
              </div>
            </div>

            {/* Sorting Sequence */}
            <div className="rounded-lg border bg-secondary/20 p-4 space-y-2">
              <h4 className="font-bold text-sm text-ink uppercase tracking-wide">Final Allocation Ordering Key</h4>
              <p className="text-sm font-mono text-ink bg-card p-2.5 rounded border">
                (Tier Rank ASC, -Effective Score DESC, Deadline Slack ASC, Booking Time ASC, PNR is None ASC, Group ID ASC)
              </p>
              <p className="text-xs text-ink-2">
                Tier comes first (Tier 0 &gt; Tier 1 &gt; Tier 2). Effective score determines ordering within tier. Deadline slack breaks score ties. Deterministic tie-breakers guarantee identical replay results.
              </p>
            </div>
          </div>
        )}

        {/* Tab 2: Formula & Interactive Sandbox */}
        {tab === 'formula' && (
          <div className="space-y-5 py-2">
            <div>
              <h3 className="text-lg font-bold text-ink">Mathematical Formula &amp; Interactive Calculator</h3>
              <p className="text-sm text-ink-2 mt-1">
                Test the exact scoring algorithm implemented in <code className="font-mono text-navy font-bold">backend/safarset/scoring/priority.py</code> with real numbers:
              </p>
            </div>

            {/* Formula LaTeX Display */}
            <div className="rounded-xl border border-navy/20 bg-navy/5 p-4 space-y-2 font-mono text-sm">
              <div className="font-bold text-navy">S_base = (W × 30 + A × 20 + U × 25 + H × 15 + D × 10) / 100</div>
              <div className="font-bold text-boarded">S_effective = S_base + (waiting_minutes × 0.1)</div>
            </div>

            {/* Interactive Calculator Inputs */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-3 rounded-xl border bg-card p-4">
                <span className="text-sm font-bold uppercase tracking-wider text-ink">Factor Scores (0–100)</span>

                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-ink-2">Waiting Time Score (W · 30%):</span>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      className="w-20 text-right font-mono h-8"
                      value={waitingTime}
                      onChange={(e) => setWaitingTime(Number(e.target.value))}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-ink-2">Age Vulnerability Score (A · 20%):</span>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      className="w-20 text-right font-mono h-8"
                      value={ageScore}
                      onChange={(e) => setAgeScore(Number(e.target.value))}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-ink-2">Journey Urgency Score (U · 25%):</span>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      className="w-20 text-right font-mono h-8"
                      value={urgencyScore}
                      onChange={(e) => setUrgencyScore(Number(e.target.value))}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-ink-2">Assistance Need Score (H · 15%):</span>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      className="w-20 text-right font-mono h-8"
                      value={assistanceScore}
                      onChange={(e) => setAssistanceScore(Number(e.target.value))}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-ink-2">Disruption Impact Score (D · 10%):</span>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      className="w-20 text-right font-mono h-8"
                      value={impactScore}
                      onChange={(e) => setImpactScore(Number(e.target.value))}
                    />
                  </div>
                  <div className="flex items-center justify-between pt-2 border-t">
                    <span className="text-ink font-semibold">Time Waited (Minutes):</span>
                    <Input
                      type="number"
                      min={0}
                      max={600}
                      className="w-20 text-right font-mono h-8"
                      value={waitingMinutes}
                      onChange={(e) => setWaitingMinutes(Number(e.target.value))}
                    />
                  </div>
                </div>
              </div>

              {/* Live Calculated Output */}
              <div className="rounded-xl border border-line bg-secondary/20 p-4 flex flex-col justify-between">
                <div>
                  <span className="text-sm font-bold uppercase tracking-wider text-ink">Live Mathematical Calculation</span>
                  <div className="mt-3 divide-y text-sm">
                    <div className="flex justify-between py-1">
                      <span>Waiting: {waitingTime} × 0.30</span>
                      <span className="font-mono">+{fmtPoints(waitingPts)}</span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span>Age: {ageScore} × 0.20</span>
                      <span className="font-mono">+{fmtPoints(agePts)}</span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span>Urgency: {urgencyScore} × 0.25</span>
                      <span className="font-mono">+{fmtPoints(urgencyPts)}</span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span>Assistance: {assistanceScore} × 0.15</span>
                      <span className="font-mono">+{fmtPoints(assistancePts)}</span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span>Impact: {impactScore} × 0.10</span>
                      <span className="font-mono">+{fmtPoints(impactPts)}</span>
                    </div>
                    <div className="flex justify-between py-1.5 font-bold text-ink">
                      <span>Base Priority Score (Subtotal):</span>
                      <span className="font-mono">{fmtPoints(baseScore)}</span>
                    </div>
                    <div className="flex justify-between py-1 text-boarded">
                      <span>Ageing: {waitingMinutes}m × 0.1 pts/min:</span>
                      <span className="font-mono font-semibold">+{fmtPoints(ageingPts)}</span>
                    </div>
                  </div>
                </div>

                <div className="mt-4 rounded-lg bg-card p-3 border-2 border-boarded text-center shadow-sm">
                  <div className="text-xs uppercase tracking-wider font-semibold text-ink-2">Final Effective Priority Score</div>
                  <div className="font-mono text-4xl font-extrabold text-boarded mt-0.5">
                    {fmtPoints(effectiveScore)}
                  </div>
                </div>
              </div>
            </div>

            {/* Note on Ageing calibration */}
            <p className="text-xs text-ink-2 italic bg-card p-3 rounded border">
              <b>Judge FAQ Note:</b> Waiting time contributes in two places by design: (1) as a normalized factor in the base model (30%), and (2) as an ongoing queue ageing mechanism (+0.1 pts/min) to prevent standard travelers from being indefinitely starved.
            </p>
          </div>
        )}

        {/* Tab 3: Group Logic & Wait Escalation */}
        {tab === 'groups_escalation' && (
          <div className="space-y-5 py-2">
            <div>
              <h3 className="text-lg font-bold text-ink">Group Integrity &amp; Starvation Prevention</h3>
              <p className="text-sm text-ink-2 mt-1">
                How SafarSet solves real-world human travel constraints: preserving traveling families and preventing queue starvation.
              </p>
            </div>

            {/* Group Rules */}
            <div className="rounded-xl border bg-card p-4 space-y-3">
              <h4 className="font-bold text-base text-ink">Group Prioritisation Rules</h4>
              <div className="grid gap-3 sm:grid-cols-2 text-sm">
                <div className="p-3 rounded-lg bg-secondary/30 space-y-1">
                  <div className="font-bold text-navy">Rule 1: Group Tier</div>
                  <p className="text-xs text-ink-2">
                    The entire group receives the <b>highest-priority tier</b> of its members.
                  </p>
                  <div className="text-xs font-mono bg-card p-1.5 rounded border">
                    Member 1 (Tier 2), Member 2 (Tier 2), Member 3 (Tier 1) → Group Tier: 1
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-secondary/30 space-y-1">
                  <div className="font-bold text-navy">Rule 2: Group Score</div>
                  <p className="text-xs text-ink-2">
                    The group score is the <b>average score</b> of members in that highest-priority tier:
                  </p>
                  <div className="text-xs font-mono bg-card p-1.5 rounded border">
                    S_group = average(member_scores in highest_priority_tier)
                  </div>
                </div>
              </div>

              {/* Anti Abuse */}
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs space-y-1 text-amber-900 dark:text-amber-200">
                <div className="font-bold uppercase tracking-wider">Anti-Abuse Companion Verification</div>
                <p>
                  To prevent travelers from artificially assembling large parties of 10 people to exploit priority inheritance from a single assistance user, groups with <b>size &gt; 4</b> require operator verification. Unverified mega-groups remain in Tier 2 until verified by station staff.
                </p>
              </div>
            </div>

            {/* Wait Escalation */}
            <div className="rounded-xl border bg-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-bold text-base text-ink">Starvation Prevention: Wait-Time Escalation</h4>
                <Pill tone="warn">Audit Event: PASSENGER_ESCALATED</Pill>
              </div>
              <p className="text-sm text-ink-2">
                Under strict tier sorting, 200+ Tier 2 passengers could be starved if alternative vehicle capacity is tight. Wait escalation provides a deterministic, auditable release valve:
              </p>

              <div className="grid gap-2 sm:grid-cols-3 text-xs">
                <div className="p-2.5 rounded bg-secondary space-y-1">
                  <div className="font-bold">1. Configurable Threshold</div>
                  <p className="text-ink-2">Tier 2 groups waiting beyond threshold (e.g. 45m demo / 120m prod) are promoted to Tier 1.</p>
                </div>
                <div className="p-2.5 rounded bg-secondary space-y-1">
                  <div className="font-bold">2. Tier 0 Invariant</div>
                  <p className="text-ink-2">Ordinary wait escalation <b>never</b> promotes someone to Tier 0 (reserved strictly for medical emergencies).</p>
                </div>
                <div className="p-2.5 rounded bg-secondary space-y-1">
                  <div className="font-bold">3. Replay Determinism</div>
                  <p className="text-ink-2">Logged as an auditable event in the append-only event log; replaying reproduces identical decisions.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 4: Database Safety & Concurrency */}
        {tab === 'database_safety' && (
          <div className="space-y-5 py-2">
            <div>
              <h3 className="text-lg font-bold text-ink">Database Safety &amp; Capacity Invariants</h3>
              <p className="text-sm text-ink-2 mt-1">
                Prioritisation is meaningless if seats are oversold. SafarSet enforces capacity at the SQLite database layer:
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 text-xs">
              <div className="rounded-xl border bg-card p-3.5 space-y-1.5">
                <span className="font-mono font-bold text-navy uppercase">1. Table Constraints</span>
                <p className="font-mono bg-secondary/50 p-1.5 rounded">CHECK(used &gt;= 0)<br />CHECK(used &lt;= cap)</p>
                <p className="text-ink-2">Database triggers reject any update that would over-allocate even a single seat.</p>
              </div>

              <div className="rounded-xl border bg-card p-3.5 space-y-1.5">
                <span className="font-mono font-bold text-navy uppercase">2. BEGIN IMMEDIATE</span>
                <p className="font-mono bg-secondary/50 p-1.5 rounded">BEGIN IMMEDIATE ... COMMIT</p>
                <p className="text-ink-2">Acquires write lock upfront; verified with 5 concurrent threads contending for the final seat: exactly 1 succeeds, 4 cleanly roll back.</p>
              </div>

              <div className="rounded-xl border bg-card p-3.5 space-y-1.5">
                <span className="font-mono font-bold text-navy uppercase">3. Multi-Segment Atomicity</span>
                <p className="font-mono bg-secondary/50 p-1.5 rounded">All-or-Nothing Journey</p>
                <p className="text-ink-2">If segment 2 of a 3-segment journey has no seats, the entire transaction rolls back. Never partially allocates a group.</p>
              </div>
            </div>

            {/* Demand Populations */}
            <div className="rounded-xl border bg-card p-4 space-y-2">
              <h4 className="font-bold text-sm text-ink uppercase tracking-wide">Separation of Demand Populations</h4>
              <div className="divide-y text-xs">
                <div className="flex justify-between py-2">
                  <span className="font-bold text-ink">Reserved PNR Passengers</span>
                  <span className="text-ink-2">Individually allocated; exact chart vacancies</span>
                </div>
                <div className="flex justify-between py-2">
                  <span className="font-bold text-ink">Ticketed Unreserved Passengers (UTS)</span>
                  <span className="text-ink-2">Individually allocated; not automatically subordinated to PNRs</span>
                </div>
                <div className="flex justify-between py-2">
                  <span className="font-bold text-ink">Estimated Walk-on Demand</span>
                  <span className="text-ink-2">Aggregated in capacity buffer planning; NEVER individually allocated</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 5: Judge Pitch Script */}
        {tab === 'pitch_script' && (
          <div className="space-y-4 py-2">
            <div className="flex items-center justify-between border-b pb-2">
              <h3 className="text-lg font-bold text-ink">Verbatim Judge Pitch Script (2 Minutes)</h3>
              <Pill tone="info">Read or speak directly to judges</Pill>
            </div>

            <div className="space-y-3.5 text-sm text-ink leading-relaxed bg-card p-5 rounded-xl border shadow-sm font-sans">
              <p>
                &ldquo;One of the biggest challenges during a mass transport disruption is that hundreds of passengers suddenly compete for scarce alternative seats. A naive first-come-first-served queue ignores who needs help most, while a black-box optimizer cannot explain its choices.&rdquo;
              </p>
              <p>
                &ldquo;To solve this, SafarSet implements an <b>explainable four-layer hybrid prioritisation algorithm</b>.
              </p>
              <p>
                <b>First, we apply hard constraints.</b> We verify that a vehicle can physically serve the passenger&apos;s destination, has sufficient remaining segment capacity, satisfies mandatory wheelchair accessibility, and keeps the traveling group intact. Hard feasibility is never overridden by a high priority score.
              </p>
              <p>
                <b>Second, we assign operational priority tiers.</b> Tier 0 is reserved for verified medical emergencies. Tier 1 is for passengers requiring additional assistance: wheelchair users, travelers with disabilities, elderly passengers who explicitly require assistance, and unaccompanied minors. Tier 2 covers all standard passengers. Hierarchical tiers guarantee critical passengers are not displaced by numerical scores.
              </p>
              <p>
                <b>Third, we calculate a weighted priority score within each tier.</b> We evaluate 5 configurable factors: waiting time (30%), age vulnerability (20%), journey urgency (25%), additional assistance (15%), and disruption impact (10%). We then add linear uncapped waiting-time ageing of 0.1 points per minute to continuously advance travelers in the queue.
              </p>
              <p>
                <b>Fourth, we prioritise groups without separation.</b> The group inherits the highest tier of its members, and scores as the average of members in that tier. Anti-abuse verification prevents artificial mega-groups from exploiting priority inheritance.
              </p>
              <p>
                To prevent standard travelers from waiting indefinitely, <b>wait-time escalation</b> automatically promotes Tier 2 passengers to Tier 1 once their wait exceeds the policy threshold, logging an auditable event in our SQLite append-only log.
              </p>
              <p>
                Finally, our greedy allocation engine reserves seats atomically using SQLite <code className="font-mono font-bold text-xs bg-secondary px-1 py-0.5 rounded">BEGIN IMMEDIATE</code> transactions and check constraints, while our <b>Why Panel</b> provides a complete mathematical and operational audit trail for every single seat.&rdquo;
              </p>
            </div>
          </div>
        )}

        <div className="flex justify-end pt-2 border-t">
          <Button size="lg" className="font-semibold" onClick={onClose}>
            Close Guide
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
