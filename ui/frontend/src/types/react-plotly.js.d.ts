// Ambient type declaration for react-plotly.js.
//
// The package ships without its own types and there is no @types/react-plotly.js
// installed, so TypeScript treats the import as implicitly `any` (TS7016). This
// gives the default-exported <Plot> component a real, if loose, prop shape — the
// underlying plotly.js types are not available in this project, so trace/layout/
// config objects are typed as open records rather than fully modelled.
declare module 'react-plotly.js' {
  import { Component, CSSProperties } from 'react';

  export interface PlotParams {
    data: Array<Record<string, unknown>>;
    layout?: Record<string, unknown>;
    config?: Record<string, unknown>;
    frames?: Array<Record<string, unknown>>;
    style?: CSSProperties;
    className?: string;
    useResizeHandler?: boolean;
    divId?: string;
    onInitialized?: (figure: unknown, graphDiv: HTMLElement) => void;
    onUpdate?: (figure: unknown, graphDiv: HTMLElement) => void;
    onPurge?: (figure: unknown, graphDiv: HTMLElement) => void;
    onError?: (err: unknown) => void;
  }

  export default class Plot extends Component<PlotParams> {}
}
