import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { LiveProvider } from '@/live/LiveProvider'
import { queryClient } from '@/lib/queryClient'
import { LiveKpis } from '@/routes/LiveKpis'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LiveProvider>
        <BrowserRouter>
          <Routes>
            <Route path="*" element={<LiveKpis />} />
          </Routes>
        </BrowserRouter>
      </LiveProvider>
    </QueryClientProvider>
  )
}
