import React from 'react';

// Jest stub for react-plotly.js. The real package eagerly loads the full
// plotly.js bundle, which does not run under jsdom, so any test that renders a
// component importing <Plot> would crash. This is wired in globally via
// `jest.moduleNameMapper` in package.json; tests that need to assert on the
// plotted data mock the module themselves with a prop-capturing factory.
const Plot: React.FC = () => <div data-testid="plot" />;

export default Plot;
