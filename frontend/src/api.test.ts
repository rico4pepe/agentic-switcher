import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  NetworkError,
  getScenarios,
  resetScenario,
  selectScenario,
  submitChat,
} from './api'
import { jsonResponse, makeResult, makeScenario } from './test/fixtures'

function mockFetch(implementation: (...args: unknown[]) => unknown) {
  const fetchMock = vi.fn(implementation)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('submitChat', () => {
  it('POSTs only the message and returns the parsed backend result', async () => {
    const result = makeResult()
    const fetchMock = mockFetch(async () => jsonResponse(result))

    const returned = await submitChat('Buy airtime')

    expect(returned).toEqual(result)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/chat')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ message: 'Buy airtime' })
  })

  it('surfaces a FastAPI string detail as an ApiError', async () => {
    mockFetch(async () => jsonResponse({ detail: 'Unsupported product type' }, 400))

    await expect(submitChat('bad')).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      message: 'Unsupported product type',
    })
  })

  it('joins FastAPI validation error detail messages', async () => {
    mockFetch(async () =>
      jsonResponse({ detail: [{ msg: 'String should have at least 1 character' }] }, 422),
    )

    const error = await submitChat('').catch((caught) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toContain('String should have at least 1 character')
  })

  it('throws NetworkError when the backend cannot be reached', async () => {
    mockFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(submitChat('hello')).rejects.toBeInstanceOf(NetworkError)
  })

  it('throws ApiError for unexpected non-JSON responses', async () => {
    mockFetch(
      async () =>
        new Response('<html>error</html>', { status: 200, headers: { 'Content-Type': 'text/html' } }),
    )

    await expect(submitChat('hello')).rejects.toMatchObject({
      name: 'ApiError',
      status: 200,
    })
  })
})

describe('scenario endpoints', () => {
  it('loads the current and available scenarios', async () => {
    const current = makeScenario()
    const available = [current]
    const fetchMock = mockFetch(async () => jsonResponse({ current, available }))

    const data = await getScenarios()

    expect(data.current.scenario).toBe('NORMAL')
    expect(data.available).toHaveLength(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/demo/scenarios')
    expect(init.method).toBe('GET')
  })

  it('selects a scenario by bounded name', async () => {
    const updated = makeScenario({ scenario: 'TIMEOUT' })
    const fetchMock = mockFetch(async () => jsonResponse(updated))

    const scenario = await selectScenario('TIMEOUT')

    expect(scenario.scenario).toBe('TIMEOUT')
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ scenario: 'TIMEOUT' })
  })

  it('resets scenarios', async () => {
    const fetchMock = mockFetch(async () => jsonResponse(makeScenario()))

    await resetScenario()

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/demo/scenarios/reset')
    expect(init.method).toBe('POST')
  })
})
