import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppHeader } from '@/components/common/AppHeader'
import { LiveProvider } from '@/live/LiveProvider'
import { queryClient } from '@/lib/queryClient'
import { OperatorPage } from '@/routes/operator/OperatorPage'

// Built in later phases (F3 field + phone, F4 demo controls + /demo).
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
            <Route path="/field" element={<Later name="Field view" />} />
            <Route path="/phone/:id" element={<Later name="Passenger phone" />} />
            <Route path="/sim" element={<Later name="Demo controls" />} />
            <Route path="/demo" element={<Later name="Demo" />} />
            <Route path="*" element={<Navigate to="/operator" replace />} />
          </Routes>
        </BrowserRouter>
      </LiveProvider>
    </QueryClientProvider>
  )
}
