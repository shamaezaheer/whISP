import { useState, useCallback } from 'react'
import axios from 'axios'

export function useApi() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const request = useCallback(async (method, path, data = null, params = null) => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios({ method, url: `/api${path}`, data, params })
      return res.data
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Request failed'
      setError(msg)
      throw err
    } finally {
      setLoading(false)
    }
  }, [])

  return {
    loading,
    error,
    get: (path, params) => request('get', path, null, params),
    post: (path, data) => request('post', path, data),
    patch: (path, data) => request('patch', path, data),
    del: (path) => request('delete', path),
  }
}
