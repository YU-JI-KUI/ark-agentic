import { Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import AgentShell from './pages/AgentShell'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/agents/:agentId/*" element={<AgentShell />} />
    </Routes>
  )
}
