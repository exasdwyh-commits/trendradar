import { Component, type ReactNode } from 'react'

/** Keep the sidebar usable if a page chunk fails to download or render. */
export class RouteBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="notice error" role="alert">
        <p>页面加载失败。请重新加载，或从侧栏进入其他页面。</p>
        <button type="button" onClick={() => window.location.reload()}>重新加载</button>
      </div>
    )
  }
}
