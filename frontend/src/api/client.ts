import axios from 'axios'

/** 统一请求封装：/api 前缀 + 响应解包（{code, message, data}）。 */
export const http = axios.create({ baseURL: '/api', timeout: 120000 })

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) return Promise.reject(new Error(body.message || '请求失败'))
      return body.data
    }
    return body
  },
  (err) => Promise.reject(new Error(err.response?.data?.detail || err.message || '网络错误')),
)

export async function get<T>(url: string, params?: object): Promise<T> {
  return http.get(url, { params }) as Promise<T>
}

export async function post<T>(url: string, data?: object, config?: object): Promise<T> {
  return http.post(url, data, config) as Promise<T>
}

export async function patch<T>(url: string, data?: object): Promise<T> {
  return http.patch(url, data) as Promise<T>
}

export async function put<T>(url: string, data?: object): Promise<T> {
  return http.put(url, data) as Promise<T>
}

export async function del<T>(url: string): Promise<T> {
  return http.delete(url) as Promise<T>
}