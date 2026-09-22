const parse = async <T,>(response: Response): Promise<T> => {
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  get: <T,>(url: string) => fetch(url).then(parse<T>),
  post: <T,>(url: string, body?: unknown) =>
    fetch(url, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).then(parse<T>),
  put: <T,>(url: string, body: unknown) =>
    fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(parse<T>),
}
