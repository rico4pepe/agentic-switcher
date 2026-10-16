import { useId, useState } from 'react'

import { classifyOutcome } from '../outcome'
import type { ConversationResponse, MCPToolCallEvent } from '../types'

interface MCPActivityPanelProps {
  response: ConversationResponse | null
  /**
   * A chat request is in flight. Per-call progress is not streamed, so while a
   * request is pending the panel reports a generic "In progress" and marks the
   * tool nodes "Waiting": it never claims a specific tool is running, and it
   * never shows a previous turn's calls as if they were the current request.
   */
  pending?: boolean
}

/**
 * How many genuine calls the collapsed panel lists inline before bounding the
 * display. The expanded MCP flow always shows the complete sequence.
 */
const MAX_INLINE_CALLS = 5

/** The MCP tools the transaction flow can use, in the order they are relevant. */
const TOOLS = [
  {
    name: 'find_transaction_capabilities',
    purpose: 'Discover which vendors can serve the request.',
  },
  {
    name: 'execute_transaction',
    purpose: 'Submit the transaction through the Switcher.',
  },
  {
    name: 'get_transaction_status',
    purpose: 'Read back the status of a transaction.',
  },
] as const

type PanelState = 'none' | 'running' | 'completed' | 'failed'
type NodeState = 'succeeded' | 'failed' | 'waiting' | 'skipped'

const PANEL_LABELS: Record<PanelState, string> = {
  none: 'No MCP activity yet',
  running: 'In progress',
  completed: 'Completed',
  failed: 'Failed',
}

const NODE_LABELS: Record<NodeState, string> = {
  succeeded: 'Succeeded',
  failed: 'Failed',
  waiting: 'Waiting',
  skipped: 'Skipped · not called',
}

function panelState(pending: boolean, events: MCPToolCallEvent[]): PanelState {
  if (pending) {
    return 'running'
  }
  if (events.some((event) => event.status === 'failed')) {
    return 'failed'
  }
  if (events.length > 0) {
    return 'completed'
  }
  return 'none'
}

function nodeState(
  tool: string,
  events: MCPToolCallEvent[],
  pending: boolean,
  terminal: boolean,
): NodeState {
  const event = events.find((candidate) => candidate.tool === tool)
  if (event) {
    return event.status === 'failed' ? 'failed' : 'succeeded'
  }
  if (pending) {
    return 'waiting'
  }
  if (terminal) {
    return 'skipped'
  }
  return 'waiting'
}

function countLabel(count: number): string {
  if (count === 0) {
    return 'No MCP calls yet.'
  }
  return `${count} MCP call${count === 1 ? '' : 's'} recorded.`
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null || Number.isNaN(durationMs)) {
    return '—'
  }
  if (durationMs >= 1000) {
    return `${(durationMs / 1000).toFixed(2)} s`
  }
  return `${Math.round(durationMs)} ms`
}

function FlowArrow({ label }: { label?: string }) {
  return (
    <div className="mcp-flow__arrow" aria-hidden="true">
      <span className="mcp-flow__arrow-glyph">↓</span>
      {label ? <span className="mcp-flow__arrow-label">{label}</span> : null}
    </div>
  )
}

/**
 * The tool nodes to render in the expanded flow: the known capability tools in
 * their canonical order, followed by any other tool the backend actually
 * recorded (so the diagram always contains the complete sequence).
 */
function flowTools(events: MCPToolCallEvent[]): Array<{ name: string; purpose: string }> {
  const known = TOOLS.map((tool) => ({ name: tool.name as string, purpose: tool.purpose }))
  const knownNames = new Set<string>(known.map((tool) => tool.name))
  const extra: Array<{ name: string; purpose: string }> = []
  for (const event of events) {
    if (!knownNames.has(event.tool) && !extra.some((tool) => tool.name === event.tool)) {
      extra.push({ name: event.tool, purpose: 'Recorded MCP tool call.' })
    }
  }
  return [...known, ...extra]
}

function ToolNode({
  name,
  purpose,
  state,
  event,
}: {
  name: string
  purpose: string
  state: NodeState
  event: MCPToolCallEvent | undefined
}) {
  return (
    <li className="mcp-tool" data-tool={name} data-state={state}>
      <div className="mcp-tool__head">
        <span className="mcp-tool__name mono">{name}</span>
        <span className="mcp-tool__status" data-state={state}>
          {NODE_LABELS[state]}
        </span>
      </div>
      <p className="mcp-tool__purpose muted">{purpose}</p>

      {event ? (
        <details className="mcp-tool__evidence">
          <summary>Inspect call</summary>
          <dl className="mcp-tool__fields">
            <div>
              <dt>Invocation</dt>
              <dd>{event.status}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{formatDuration(event.duration_ms)}</dd>
            </div>
            <div>
              <dt>Transaction ID</dt>
              <dd className="mono">{event.transaction_id ?? '—'}</dd>
            </div>
            <div className="mcp-tool__field--wide">
              <dt>Arguments (sanitized)</dt>
              <dd>
                <pre>{JSON.stringify(event.arguments, null, 2)}</pre>
              </dd>
            </div>
            <div className="mcp-tool__field--wide">
              <dt>{event.status === 'failed' ? 'Error' : 'Result'}</dt>
              <dd>
                {event.status === 'failed' ? (
                  event.error ?? '—'
                ) : (
                  <pre>{JSON.stringify(event.result, null, 2)}</pre>
                )}
              </dd>
            </div>
          </dl>
        </details>
      ) : null}
    </li>
  )
}

/**
 * The live MCP flow panel.
 *
 * It shows the *actual* MCP tool calls the backend made while producing the
 * current result, in order — never a scenario, a status, or an available tool
 * presented as activity. While a request is in flight, per-tool progress is not
 * available, so the panel states plainly that a request is in progress and the
 * tool nodes wait rather than claiming a specific call is running.
 *
 * Collapsed, it shows the heading, a truthful state, the count of real calls, a
 * compact inline list of those calls in their actual execution order (each with
 * its invocation status), and the disclosure control. Expanded, it shows the
 * request → orchestration → MCP interface → tool calls → recorded result flow,
 * with each node inspectable down to its sanitized arguments, result or error,
 * duration, and transaction id. Tools that were merely available are never
 * listed: only recorded invocations appear.
 */
export function MCPActivityPanel({
  response,
  pending = false,
}: MCPActivityPanelProps) {
  const [expanded, setExpanded] = useState(false)
  const detailsId = useId()

  const result = response?.result ?? null
  const step = response?.step ?? null
  const terminal = !pending && (step === 'complete' || step === 'cancelled')
  // A pending request owns no evidence yet: ignore a previous turn's calls so
  // they are never shown as the current request's activity.
  const events = pending ? [] : (result?.mcp_events ?? [])
  const state = panelState(pending, events)

  const resultDetail = result
    ? `Outcome: ${classifyOutcome(result.status).label}`
    : 'Waiting for a transaction result.'

  // Real recorded calls, in their actual execution order (already ordered by the
  // backend). Bounded inline; the expanded flow lists them all.
  const inlineCalls = events.slice(0, MAX_INLINE_CALLS)
  const hiddenCallCount = events.length - inlineCalls.length

  return (
    <section className="card mcp-activity" aria-label="MCP activity">
      <div className="mcp-activity__heading">
        <h2>MCP activity</h2>
        <span className="mcp-activity__state" data-state={state}>
          <span className="mcp-activity__dot" aria-hidden="true" />
          {PANEL_LABELS[state]}
        </span>
      </div>

      <p className="muted mcp-activity__count">{countLabel(events.length)}</p>

      {inlineCalls.length > 0 && (
        <ul className="mcp-call-list" aria-label="Recorded MCP calls">
          {inlineCalls.map((event) => (
            <li
              key={`${event.sequence}-${event.tool}`}
              className="mcp-call"
              data-state={event.status}
            >
              <span className="mcp-call__seq" aria-hidden="true">
                {event.sequence}
              </span>
              <span className="mcp-call__name mono">{event.tool}</span>
              <span className="mcp-call__status" data-state={event.status}>
                {event.status === 'failed' ? 'Failed' : 'Succeeded'}
              </span>
            </li>
          ))}
          {hiddenCallCount > 0 && (
            <li className="mcp-call mcp-call--more">
              +{hiddenCallCount} more shown in the MCP flow
            </li>
          )}
        </ul>
      )}

      <button
        type="button"
        className="trace-disclosure mcp-activity__disclosure"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((value) => !value)}
      >
        <span
          className="trace-disclosure__chevron"
          data-expanded={expanded}
          aria-hidden="true"
        >
          ▸
        </span>
        {expanded ? 'Hide MCP flow' : 'Show MCP flow'}
      </button>

      <div
        id={detailsId}
        className="mcp-flow"
        data-active={pending}
        hidden={!expanded}
      >
        <div className="mcp-flow__stage" data-stage="request">
          <span className="mcp-flow__stage-label">Transaction request</span>
          <span className="mcp-flow__stage-detail muted">
            The user&rsquo;s intent, parsed by the assistant.
          </span>
        </div>

        <FlowArrow label="request" />

        <div className="mcp-flow__stage" data-stage="orchestration">
          <span className="mcp-flow__stage-label">
            Policy &amp; transaction orchestration
          </span>
          <span className="mcp-flow__stage-detail muted">
            The Switcher selects a vendor and decides whether to proceed.
          </span>
        </div>

        <FlowArrow />

        <div className="mcp-flow__stage" data-stage="interface">
          <span className="mcp-flow__stage-label">MCP interface</span>
          <span className="mcp-flow__stage-detail muted">
            Tools are invoked over the in-process MCP session.
          </span>
        </div>

        <FlowArrow />

        <ul className="mcp-tools" aria-label="MCP tool calls">
          {flowTools(events).map((tool) => (
            <ToolNode
              key={tool.name}
              name={tool.name}
              purpose={tool.purpose}
              state={nodeState(tool.name, events, pending, terminal)}
              event={events.find((candidate) => candidate.tool === tool.name)}
            />
          ))}
        </ul>

        <FlowArrow label="response" />

        <div className="mcp-flow__stage" data-stage="result">
          <span className="mcp-flow__stage-label">Recorded result</span>
          <span className="mcp-flow__stage-detail muted">{resultDetail}</span>
        </div>
      </div>
    </section>
  )
}
