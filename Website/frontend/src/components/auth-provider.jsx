import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  changePassword as apiChangePassword,
  clearToken,
  fetchMe,
  getToken,
  login as apiLogin,
  setToken,
  setUserRole,
} from '@/lib/api'

const AuthContext = createContext(null)

function shouldPromptPasswordChange(user) {
  return Boolean(user?.temp_login && user?.role && user.role !== 'siteadmin')
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [features, setFeatures] = useState({ show_exception_uploads: false })
  const [loading, setLoading] = useState(true)
  const [passwordChangeOpen, setPasswordChangeOpen] = useState(false)

  const refreshUser = useCallback(async () => {
    const token = getToken()
    if (!token) {
      setUser(null)
      setFeatures({ show_exception_uploads: false })
      setUserRole(null)
      setPasswordChangeOpen(false)
      setLoading(false)
      return null
    }
    try {
      const data = await fetchMe()
      setUser(data.user)
      setFeatures({
        show_exception_uploads: Boolean(data.features?.show_exception_uploads),
      })
      setUserRole(data.user?.role)
      return data.user
    } catch {
      clearToken()
      setUser(null)
      setFeatures({ show_exception_uploads: false })
      setPasswordChangeOpen(false)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshUser()
  }, [refreshUser])

  const login = useCallback(async (email, password) => {
    const data = await apiLogin(email, password)
    setToken(data.token)
    setUser(data.user)
    setFeatures({
      show_exception_uploads: Boolean(data.features?.show_exception_uploads),
    })
    setUserRole(data.user?.role)
    setPasswordChangeOpen(shouldPromptPasswordChange(data.user))
    return data.user
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
    setFeatures({ show_exception_uploads: false })
    setPasswordChangeOpen(false)
  }, [])

  const dismissPasswordChange = useCallback(() => {
    setPasswordChangeOpen(false)
  }, [])

  const changePassword = useCallback(async ({ currentPassword, newPassword }) => {
    const data = await apiChangePassword({
      current_password: currentPassword,
      new_password: newPassword,
    })
    setUser(data.user)
    setPasswordChangeOpen(false)
    return data.user
  }, [])

  const value = useMemo(
    () => ({
      user,
      features,
      showExceptionUploads: Boolean(features?.show_exception_uploads),
      loading,
      isAuthenticated: Boolean(user),
      isSiteAdmin: user?.role === 'siteadmin',
      canWrite: user?.role === 'snt',
      passwordChangeOpen,
      login,
      logout,
      refreshUser,
      dismissPasswordChange,
      changePassword,
    }),
    [
      user,
      features,
      loading,
      passwordChangeOpen,
      login,
      logout,
      refreshUser,
      dismissPasswordChange,
      changePassword,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
