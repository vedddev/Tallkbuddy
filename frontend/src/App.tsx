import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { LoadingState } from './components/ui/Primitives'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { AuthPage } from './pages/AuthPage'
import { HistoryPage, SessionDetailPage } from './pages/HistoryPage'
import { LandingPage } from './pages/LandingPage'
import { SettingsPage } from './pages/SettingsPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { MeetingPage } from './pages/MeetingPage'
import { OverviewPage } from './pages/OverviewPage'
import { TranslatePage } from './pages/TranslatePage'

function PrivatePage({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="grid min-h-screen place-items-center bg-canvas text-foreground"><LoadingState label="Checking your session..." /></div>
  if (!user) return <Navigate to="/login" replace />
  return <AppShell>{children}</AppShell>
}

function WorkspaceRoute() {
  const { hash } = useLocation()
  if (hash === '#meeting') return <Navigate to="/meeting" replace />
  if (hash === '#translate') return <Navigate to="/translate" replace />
  return <WorkspacePage />
}

export function App() {
  return <ThemeProvider><BrowserRouter><AuthProvider><Routes>
    <Route path="/" element={<LandingPage />} />
    <Route path="/login" element={<AuthPage mode="login" />} />
    <Route path="/register" element={<AuthPage mode="register" />} />
    <Route path="/overview" element={<PrivatePage><OverviewPage /></PrivatePage>} />
    <Route path="/translate" element={<PrivatePage><TranslatePage /></PrivatePage>} />
    <Route path="/workspace" element={<PrivatePage><WorkspaceRoute /></PrivatePage>} />
    <Route path="/meeting" element={<PrivatePage><MeetingPage /></PrivatePage>} />
    <Route path="/history" element={<PrivatePage><HistoryPage /></PrivatePage>} />
    <Route path="/history/:sessionId" element={<PrivatePage><SessionDetailPage /></PrivatePage>} />
    <Route path="/settings" element={<PrivatePage><SettingsPage /></PrivatePage>} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></AuthProvider></BrowserRouter></ThemeProvider>
}
