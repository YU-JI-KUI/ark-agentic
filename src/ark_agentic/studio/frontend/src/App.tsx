import { Routes, Route, Navigate } from 'react-router-dom'
import StudioLayout from './layouts/StudioLayout'
import DashboardWelcome from './pages/DashboardWelcome'
import AgentDetail, { SkillsViewTab, ToolsViewTab, SessionsViewTab, MemoryViewTab } from './pages/AgentDetail'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<StudioLayout />}>
        <Route index element={<DashboardWelcome />} />
        <Route path="agents/:agentId" element={<AgentDetail />}>
          <Route index element={<Navigate to="skills" replace />} />
          <Route path="skills" element={<SkillsViewTab />} />
          <Route path="tools" element={<ToolsViewTab />} />
          <Route path="sessions" element={<SessionsViewTab />} />
          <Route path="memory" element={<MemoryViewTab />} />
        </Route>
      </Route>
    </Routes>
  )
}
