import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ProgressDisplay } from './ProgressDisplay'

describe('ProgressDisplay', () => {
  it('animates only the fill for an exposure without a target', () => {
    const { container } = render(
      <ProgressDisplay progress={{ mode: 'indeterminate', current: null, target: null, unit: null, percent: null }} />,
    )

    const panel = screen.getByText('Exposure progress').closest('.progress-display')
    const fill = container.querySelector('.progress-fill')

    expect(panel).toHaveClass('progress-mode-indeterminate')
    expect(panel).not.toHaveClass('is-indeterminate')
    expect(fill).toHaveClass('is-indeterminate')
  })
})