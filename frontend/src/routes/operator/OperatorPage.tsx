import { useState } from 'react'
import { AppHeader } from '@/components/common/AppHeader'
import { ErrorNote, Loading, NoScenario } from '@/components/common/Panels'
import { useAppState } from '@/hooks/useAppState'
import { ApprovalPanel } from './ApprovalPanel'
import { ConflictsPanel } from './ConflictsPanel'
import { CapacityPanel } from './CapacityPanel'
import { DisruptionBanner } from './DisruptionBanner'
import { EventLog } from './EventLog'
import { KpiTiles } from './KpiTiles'
import { PassengerTable } from './PassengerTable'
import { PriorityOverview } from './PriorityOverview'
import { UNRESOLVED_ANCHOR } from './reviewModel'
import { RulesPanel } from './RulesPanel'
import { UnresolvedPanel } from './UnresolvedPanel'
import { WhyPanel } from './WhyPanel'

export function OperatorPage() {
  const { data, error, isLoading } = useAppState()
  const [selected, setSelected] = useState<string | null>(null)
  // a group picked from the approval panel is explained far below it, so bring the explanation into view
  const explain = (groupId: string) => {
    setSelected(groupId)
    setTimeout(() => document.getElementById('why-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0)
  }
  return (
    <>
      <AppHeader subtitle="Control room" />
      <main className="mx-auto max-w-[1840px] space-y-5 px-6 py-5">
        <ErrorNote error={error} />
        {isLoading && <Loading what="dashboard" />}
        {data && !data.loaded && <NoScenario />}
        {data?.loaded && (
          <>
            <DisruptionBanner state={data} />
            <PriorityOverview overview={data.kpis.priority_overview} />
            <KpiTiles kpis={data.kpis} />
            <ApprovalPanel onSelect={explain} />
            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
              <CapacityPanel />
              <div className="space-y-5">
                <PassengerTable selected={selected} onSelect={setSelected} />
                <div id="why-panel"><WhyPanel groupId={selected} onSelect={setSelected} /></div>
              </div>
            </div>
            <ConflictsPanel />
            <div className="grid items-start gap-5 lg:grid-cols-3">
              <div id={UNRESOLVED_ANCHOR} className="scroll-mt-24"><UnresolvedPanel onSelect={setSelected} /></div>
              <RulesPanel />
              <EventLog />
            </div>
          </>
        )}
      </main>
    </>
  )
}
