import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppHeader } from '@/components/common/AppHeader'
import { LiveProvider } from '@/live/LiveProvider'
import { queryClient } from '@/lib/queryClient'
import { FieldPage } from '@/routes/field/FieldPage'
import { OperatorPage } from '@/routes/operator/OperatorPage'
import { PhonePage } from '@/routes/phone/PhonePage'

// Built in F4: demo controls and the /demo page.
function Later({ name }: { name: string }) {
  return (
    <>
      <AppHeader subtitle={name} />
      <p className="p-6 text-ink-2">{name} is not built yet.</p>
    </>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LiveProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Navigate to="/operator" replace />} />
            <Route path="/operator" element={<OperatorPage />} />
            <Route path="/field" element={<FieldPage />} />
            <Route path="/phone" element={<PhonePage />} />
            <Route path="/phone/:id" element={<PhonePage />} />
            <Route path="/sim" element={<Later name="Demo controls" />} />
            <Route path="/demo" element={<Later name="Demo" />} />
            <Route path="*" element={<Navigate to="/operator" replace />} />
          </Routes>
        </BrowserRouter>
      </LiveProvider>
    </QueryClientProvider>
  )
}
