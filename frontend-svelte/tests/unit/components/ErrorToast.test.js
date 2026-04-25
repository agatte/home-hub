import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import { tick } from 'svelte'

import ErrorToast from '$lib/components/ErrorToast.svelte'
import { errors, addError } from '$lib/stores/errors.js'

beforeEach(() => {
  errors.set([])
})

afterEach(() => {
  errors.set([])
})

describe('ErrorToast', () => {
  it('renders nothing when there are no errors', () => {
    const { container } = render(ErrorToast)
    expect(container.querySelectorAll('.error-toast')).toHaveLength(0)
  })

  it('renders an error message when one is added', async () => {
    render(ErrorToast)
    addError('Something broke')
    await tick()
    expect(screen.getByText('Something broke')).toBeInTheDocument()
  })

  it('toast carries live-region a11y attributes for screen readers', async () => {
    const { container } = render(ErrorToast)
    addError('boom')
    await tick()
    const toast = container.querySelector('.error-toast')
    expect(toast).toBeInTheDocument()
    // live region: role + aria-live + aria-atomic so SR announces the
    // full toast text on insertion. (role=status is the polite-priority
    // analog of alert and is the right fit for non-critical app errors.)
    expect(toast).toHaveAttribute('role', 'status')
    expect(toast).toHaveAttribute('aria-live', 'polite')
    expect(toast).toHaveAttribute('aria-atomic', 'true')
  })

  it('renders one toast per error in the store', async () => {
    const { container } = render(ErrorToast)
    addError('one')
    addError('two')
    await tick()
    expect(container.querySelectorAll('.error-toast')).toHaveLength(2)
  })
})
