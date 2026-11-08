import { Component } from 'react';
import type { ReactNode } from 'react';

export default class ChartBoundary extends Component<{ children: ReactNode; title?: string; message?: string; recovery?: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <section className="feedback feedback-error" role="alert">
      <h2>{this.props.title ?? 'Price chart unavailable'}</h2>
      <p>{this.props.message ?? 'Open “View all 40 forecast quarters” below for the full price table. Reload the page to try loading the chart again.'}</p>
      {this.props.recovery}
    </section>;
    return this.props.children;
  }
}
