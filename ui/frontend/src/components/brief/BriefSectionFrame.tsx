import React from 'react';

type Props = React.HTMLAttributes<HTMLElement> & { researching: boolean };

/** Keep the heading in place when its research controls and draft exchange places. */
export class BriefSectionFrame extends React.Component<Props> {
  private element = React.createRef<HTMLElement>();

  getSnapshotBeforeUpdate(previous: Props): number | null {
    const section = this.element.current;
    if (!section || previous.researching === this.props.researching ||
        !section.contains(document.activeElement)) return null;
    const bounds = section.getBoundingClientRect();
    return bounds.bottom > 0 && bounds.top < window.innerHeight ? bounds.top : null;
  }

  componentDidUpdate(_previous: Props, _state: unknown, top: number | null) {
    if (top === null || !this.element.current) return;
    const distance = this.element.current.getBoundingClientRect().top - top;
    if (distance) window.scrollBy({ top: distance, behavior: 'auto' });
  }

  render() {
    const { researching, ...attributes } = this.props;
    return <section {...attributes} ref={this.element} />;
  }
}
