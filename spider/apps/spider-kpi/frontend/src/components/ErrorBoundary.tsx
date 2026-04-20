import React from 'react'

export class ErrorBoundary extends React.Component<
  { label?: string; children: React.ReactNode },
  { hasError: boolean; message?: string }
> {
  constructor(props: { label?: string; children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, message: undefined }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error.message }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[kpi-ui] render_error', {
      label: this.props.label || 'unknown',
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
    })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="card">
          <div className="card-title">Component Error</div>
          <div className="state-message error">
            {this.props.label || 'This section'} failed to render cleanly.
            {this.state.message ? ` ${this.state.message}` : ''}
          </div>
          <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="range-button active"
              onClick={() => this.setState({ hasError: false, message: undefined })}
            >
              Retry
            </button>
            <button
              type="button"
              className="range-button"
              onClick={() => window.location.reload()}
            >
              Reload page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
