import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

const getComputedStyle = window.getComputedStyle.bind(window)

Object.defineProperty(window, 'getComputedStyle', {
  writable: true,
  value: (element: Element) => getComputedStyle(element),
})

afterEach(() => {
  cleanup()
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
})

class ResizeObserverMock {
  observe() {
    return undefined
  }

  unobserve() {
    return undefined
  }

  disconnect() {
    return undefined
  }
}

Object.defineProperty(window, 'ResizeObserver', {
  writable: true,
  value: ResizeObserverMock,
})
