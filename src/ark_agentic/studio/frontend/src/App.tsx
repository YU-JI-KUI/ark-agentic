import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import StudioShell from './layouts/StudioShell'
import AgentWorkspacePage from './pages/AgentWorkspacePage'
import LoginPage from './pages/LoginPage'
import StudioDashboardPage from './pages/StudioDashboardPage'
import UsersPage from './pages/UsersPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<StudioShell />}>
          <Route index element={<StudioDashboardPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="agents/:agentId" element={<Navigate to="overview" replace />} />
          <Route path="agents/:agentId/:section" element={<AgentWorkspacePage />} />
        </Route>
      </Route>
    </Routes>
  )
}
