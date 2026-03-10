import { useState, useEffect, createContext, useContext } from 'react'
import axios from 'axios'

const AuthContext = createContext(null)

// Set header synchronously at module load so it is present before any
// child component useEffect fires (children effects run before parents).
const _initialToken = localStorage.getItem('whisp_token')
if (_initialToken) {
  axios.defaults.headers.common['Authorization'] = `Bearer ${_initialToken}`
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(_initialToken)
  const [user, setUser] = useState(() => {
    try {
      const u = localStorage.getItem('whisp_user')
      return u ? JSON.parse(u) : null
    } catch { return null }
  })

  useEffect(() => {
    if (token) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
    } else {
      delete axios.defaults.headers.common['Authorization']
    }
  }, [token])

  // 401 interceptor
  useEffect(() => {
    const id = axios.interceptors.response.use(
      r => r,
      err => {
        if (err.response?.status === 401) {
          logout()
          window.location.href = '/'
        }
        return Promise.reject(err)
      }
    )
    return () => axios.interceptors.response.eject(id)
  }, [])

  const login = async (email, password) => {
    const { data } = await axios.post('/api/auth/login', {
      email, password, actor_type: 'franchisee'
    })
    setToken(data.access_token)
    setUser(data.user)
    localStorage.setItem('whisp_token', data.access_token)
    localStorage.setItem('whisp_user', JSON.stringify(data.user))
    axios.defaults.headers.common['Authorization'] = `Bearer ${data.access_token}`
    return data
  }

  const logout = () => {
    setToken(null)
    setUser(null)
    localStorage.removeItem('whisp_token')
    localStorage.removeItem('whisp_user')
    delete axios.defaults.headers.common['Authorization']
  }

  return (
    <AuthContext.Provider value={{ token, user, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
