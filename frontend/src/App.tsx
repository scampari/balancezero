import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { BudgetPage } from './pages/BudgetPage'
import { LoginPage } from './pages/LoginPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/budget" element={<BudgetPage />} />
          <Route path="/" element={<Navigate to="/budget" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
