import { Component } from 'react';
import type { ReactNode } from 'react';

export default class ChartBoundary extends Component<{ children: ReactNode; title?: string; message?: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <section className="feedback feedback-error" role="alert">
      <h2>{this.props.title ?? 'Price chart unavailable'}</h2>
      <p>{this.props.message ?? 'The full forecast is available in the table below. Reload the page to try loading the chart again.'}</p>
    </section>;
    return this.props.children;
  }
}
