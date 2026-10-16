/**
 * Catches a render throw and shows the verbatim message in place, rather than blanking the
 * app (RFC B1: never NaN/blank/throw to the user). Mirrors the leaderboard's ErrorBoundary.
 */
import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  resetKey?: unknown
}
interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="viewerror" role="alert">
          <h3>The dashboard could not render this snapshot.</h3>
          <pre>
            <code>{this.state.error.message}</code>
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}
