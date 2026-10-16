import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import {
  makeConversation,
  makeDraft,
  makeMCPEvent,
  makeResult,
} from '../test/fixtures'
import { MCPActivityPanel } from './MCPActivityPanel'

function completedResponse(result = makeResult({ mcp_events: [] })) {
  return makeConversation({
    step: 'complete',
    prompt: 'Confirmed. Submitting the transaction.',
    missing_fields: [],
    draft: makeDraft({
      network: 'MTN',
      beneficiary: '08030000001',
      amount: '5000.00',
    }),
    result,
  })
}

function flowRegion(): HTMLElement | null {
  return document.querySelector('.mcp-flow')
}

function toolNode(name: string): HTMLElement | null {
  return document.querySelector(`[data-tool="${name}"]`)
}

function inlineCalls(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll('.mcp-call-list .mcp-call:not(.mcp-call--more)'),
  )
}

function inlineNames(): string[] {
  return inlineCalls().map(
    (call) => call.querySelector('.mcp-call__name')?.textContent ?? '',
  )
}

describe('MCPActivityPanel', () => {
  it('reports no activity before any request and hides the flow', () => {
    render(<MCPActivityPanel response={null} />)

    const panel = screen.getByLabelText('MCP activity')
    expect(within(panel).getByText('No MCP activity yet')).toBeInTheDocument()
    expect(within(panel).getByText('No MCP calls yet.')).toBeInTheDocument()
    expect(
      within(panel).getByRole('button', { name: /show mcp flow/i }),
    ).toHaveAttribute('aria-expanded', 'false')
    expect(flowRegion()).toHaveAttribute('hidden')
  })

  it('reports a generic in-progress state without claiming a tool ran', () => {
    render(<MCPActivityPanel response={null} pending />)

    const panel = screen.getByLabelText('MCP activity')
    expect(within(panel).getByText('In progress')).toBeInTheDocument()
    expect(within(panel).getByText('No MCP calls yet.')).toBeInTheDocument()
  })

  it('never shows a previous turn’s calls as the current request’s activity', () => {
    const previous = completedResponse(
      makeResult({
        mcp_events: [
          makeMCPEvent({ tool: 'find_transaction_capabilities' }),
          makeMCPEvent({ sequence: 2, tool: 'execute_transaction' }),
        ],
      }),
    )
    render(<MCPActivityPanel response={previous} pending />)

    const panel = screen.getByLabelText('MCP activity')
    expect(within(panel).getByText('In progress')).toBeInTheDocument()
    expect(within(panel).getByText('No MCP calls yet.')).toBeInTheDocument()
  })

  it('reports completion with a truthful count of real calls', () => {
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            mcp_events: [
              makeMCPEvent({ tool: 'find_transaction_capabilities' }),
              makeMCPEvent({ sequence: 2, tool: 'execute_transaction' }),
            ],
          }),
        )}
      />,
    )

    const panel = screen.getByLabelText('MCP activity')
    expect(within(panel).getByText('Completed')).toBeInTheDocument()
    expect(within(panel).getByText('2 MCP calls recorded.')).toBeInTheDocument()
  })

  it('reports failure when a call failed', () => {
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            status: 'unknown',
            mcp_events: [
              makeMCPEvent({ tool: 'find_transaction_capabilities' }),
              makeMCPEvent({
                sequence: 2,
                tool: 'execute_transaction',
                status: 'failed',
                result: null,
                error: 'Transaction execution could not be completed',
              }),
            ],
          }),
        )}
      />,
    )

    const panel = screen.getByLabelText('MCP activity')
    expect(
      within(panel).getByText('Failed', { selector: '.mcp-activity__state' }),
    ).toBeInTheDocument()
  })

  it('reveals the flow on demand behind an accessible disclosure', async () => {
    const user = userEvent.setup()
    render(<MCPActivityPanel response={completedResponse()} />)

    const toggle = screen.getByRole('button', { name: /show mcp flow/i })
    const flow = flowRegion()
    expect(flow).not.toBeNull()
    expect(toggle).toHaveAttribute('aria-controls', (flow as HTMLElement).id)
    expect(flow).not.toBeVisible()

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveTextContent(/hide mcp flow/i)
    expect(flowRegion()).not.toHaveAttribute('hidden')
    expect(flowRegion()).toBeVisible()
  })

  it('maps the real calls to tool nodes and marks unused tools skipped', async () => {
    const user = userEvent.setup()
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            mcp_events: [
              makeMCPEvent({
                tool: 'find_transaction_capabilities',
                duration_ms: 8.2,
              }),
              makeMCPEvent({
                sequence: 2,
                tool: 'execute_transaction',
                transaction_id: 'txn-1',
                arguments: {
                  beneficiary: '080******01',
                  idempotency_key: '[redacted]',
                  amount: '5000',
                  vendor_code: 'vendor_a',
                },
                result: { transaction_id: 'txn-1', status: 'success' },
                duration_ms: 42,
              }),
            ],
          }),
        )}
      />,
    )

    await user.click(screen.getByRole('button', { name: /show mcp flow/i }))

    const find = toolNode('find_transaction_capabilities')
    const execute = toolNode('execute_transaction')
    const status = toolNode('get_transaction_status')
    expect(find).not.toBeNull()
    expect(execute).not.toBeNull()

    expect(within(find as HTMLElement).getByText('Succeeded')).toBeInTheDocument()
    expect(
      within(execute as HTMLElement).getByText('Succeeded'),
    ).toBeInTheDocument()
    expect(
      within(status as HTMLElement).getByText(/skipped/i),
    ).toBeInTheDocument()
    // The unused tool shows no fabricated evidence.
    expect(
      within(status as HTMLElement).queryByText(/inspect call/i),
    ).not.toBeInTheDocument()
  })

  it('lets a call be inspected down to its sanitized evidence', async () => {
    const user = userEvent.setup()
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            mcp_events: [
              makeMCPEvent({
                tool: 'execute_transaction',
                transaction_id: 'txn-1',
                arguments: {
                  beneficiary: '080******01',
                  idempotency_key: '[redacted]',
                },
                result: { transaction_id: 'txn-1', status: 'success' },
                duration_ms: 42,
              }),
            ],
          }),
        )}
      />,
    )

    await user.click(screen.getByRole('button', { name: /show mcp flow/i }))

    const execute = toolNode('execute_transaction') as HTMLElement
    await user.click(within(execute).getByText(/inspect call/i))

    expect(within(execute).getByText('Invocation')).toBeInTheDocument()
    expect(within(execute).getByText('42 ms')).toBeInTheDocument()
    expect(within(execute).getByText('txn-1')).toBeInTheDocument()
    const args = within(execute).getByText('Arguments (sanitized)')
    expect(args.nextElementSibling).toHaveTextContent('[redacted]')
    expect(args.nextElementSibling).toHaveTextContent('080******01')
  })

  it('presents a failed call’s error instead of a result', async () => {
    const user = userEvent.setup()
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            status: 'unknown',
            mcp_events: [
              makeMCPEvent({
                tool: 'execute_transaction',
                status: 'failed',
                result: null,
                error: 'MCP tool execute_transaction returned an error',
              }),
            ],
          }),
        )}
      />,
    )

    await user.click(screen.getByRole('button', { name: /show mcp flow/i }))

    const execute = toolNode('execute_transaction') as HTMLElement
    await user.click(within(execute).getByText(/inspect call/i))
    expect(within(execute).getByText('Error')).toBeInTheDocument()
    expect(
      within(execute).getByText('MCP tool execute_transaction returned an error'),
    ).toBeInTheDocument()
  })

  it('marks nodes waiting (not running) while a request is pending', async () => {
    const user = userEvent.setup()
    render(<MCPActivityPanel response={null} pending />)

    await user.click(screen.getByRole('button', { name: /show mcp flow/i }))

    const find = toolNode('find_transaction_capabilities') as HTMLElement
    expect(within(find).getByText('Waiting')).toBeInTheDocument()
    expect(within(find).queryByText('Succeeded')).not.toBeInTheDocument()
  })

  it('shows a denial as completed discovery with no execution call', async () => {
    const user = userEvent.setup()
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            status: 'denied',
            action: 'deny',
            transaction_id: null,
            vendor_code: null,
            vendor_reference: null,
            planner_candidate_vendor: 'vendor_a',
            reason: 'Insufficient balance',
            mcp_events: [makeMCPEvent({ tool: 'find_transaction_capabilities' })],
          }),
        )}
      />,
    )

    const panel = screen.getByLabelText('MCP activity')
    expect(within(panel).getByText('Completed')).toBeInTheDocument()
    expect(within(panel).getByText('1 MCP call recorded.')).toBeInTheDocument()

    await user.click(within(panel).getByRole('button', { name: /show mcp flow/i }))
    const execute = toolNode('execute_transaction') as HTMLElement
    expect(within(execute).getByText(/skipped/i)).toBeInTheDocument()
  })

  it('lists the real recorded calls inline, in execution order, while collapsed', () => {
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            mcp_events: [
              makeMCPEvent({ sequence: 1, tool: 'find_transaction_capabilities' }),
              makeMCPEvent({ sequence: 2, tool: 'execute_transaction' }),
            ],
          }),
        )}
      />,
    )

    // The flow is not expanded, yet the calls are listed.
    expect(flowRegion()).toHaveAttribute('hidden')
    expect(inlineNames()).toEqual([
      'find_transaction_capabilities',
      'execute_transaction',
    ])
    for (const call of inlineCalls()) {
      expect(
        within(call).getByText('Succeeded', { selector: '.mcp-call__status' }),
      ).toBeInTheDocument()
    }
  })

  it('shows no inline entries when the backend recorded no calls', () => {
    render(
      <MCPActivityPanel
        response={completedResponse(makeResult({ mcp_events: [] }))}
      />,
    )

    expect(inlineCalls()).toHaveLength(0)
    expect(document.querySelector('.mcp-call-list')).toBeNull()
  })

  it('shows a truthful Failed status for a failed call inline', () => {
    render(
      <MCPActivityPanel
        response={completedResponse(
          makeResult({
            status: 'unknown',
            mcp_events: [
              makeMCPEvent({
                tool: 'execute_transaction',
                status: 'failed',
                result: null,
                error: 'MCP tool execute_transaction returned an error',
              }),
            ],
          }),
        )}
      />,
    )

    const call = inlineCalls()[0]
    expect(call).toHaveAttribute('data-state', 'failed')
    expect(
      within(call).getByText('Failed', { selector: '.mcp-call__status' }),
    ).toBeInTheDocument()
    // A failed call never shows a success indicator.
    expect(
      within(call).queryByText('Succeeded', { selector: '.mcp-call__status' }),
    ).not.toBeInTheDocument()
  })

  it('bounds the inline list while the expanded flow keeps the complete sequence', async () => {
    const user = userEvent.setup()
    const many = Array.from({ length: 7 }, (_, index) =>
      makeMCPEvent({
        sequence: index + 1,
        tool: `tool_${index + 1}`,
      }),
    )
    render(
      <MCPActivityPanel
        response={completedResponse(makeResult({ mcp_events: many }))}
      />,
    )

    // The inline list is bounded.
    expect(inlineNames()).toEqual([
      'tool_1',
      'tool_2',
      'tool_3',
      'tool_4',
      'tool_5',
    ])
    const more = document.querySelector('.mcp-call--more')
    expect(more).not.toBeNull()
    expect(more).toHaveTextContent('+2 more')

    // The expanded flow still contains every recorded call.
    await user.click(screen.getByRole('button', { name: /show mcp flow/i }))
    for (let index = 1; index <= 7; index += 1) {
      expect(toolNode(`tool_${index}`)).not.toBeNull()
    }
  })
})
