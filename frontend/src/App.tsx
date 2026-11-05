import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { LiveProvider } from '@/live/LiveProvider'
import { queryClient } from '@/lib/queryClient'
import { DemoPage } from '@/routes/demo/DemoPage'
import { FieldPage } from '@/routes/field/FieldPage'
import { OperatorPage } from '@/routes/operator/OperatorPage'
import { PhonePage } from '@/routes/phone/PhonePage'
import { SimPage } from '@/routes/sim/SimPage'

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
            <Route path="/sim" element={<SimPage />} />
            <Route path="/demo" element={<DemoPage />} />
            <Route path="*" element={<Navigate to="/operator" replace />} />
          </Routes>
        </BrowserRouter>
      </LiveProvider>
    </QueryClientProvider>
  )
}
