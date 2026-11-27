import { App } from '@modelcontextprotocol/ext-apps/app-with-deps';

const app = new App({ name: 'Evidence Lab Heatmapper', version: '1.0.0' });
const element = (id) => document.getElementById(id);
const controls = element('controls');
const rowPicker = element('rows');
const columnPicker = element('columns');
const details = element('details');
const gridViewport = element('viewport');
const documents = element('documents');

let grid;
let selected;
let generation = 0;

function showStatus(message) {
  element('status').textContent = message;
}

function create(tag, label, parent) {
  const node = document.createElement(tag);
  if (label !== null) node.textContent = label;
  parent.append(node);
  return node;
}

function populatePicker(picker, options, current) {
  picker.replaceChildren();
  for (const [key, label] of Object.entries(options)) {
    const option = create('option', label, picker);
    option.value = key;
  }
  picker.value = current;
}

function syncPickers() {
  element('query-field').hidden = rowPicker.value !== 'queries';
  for (const option of columnPicker.options) option.disabled = option.value === rowPicker.value;
  element('generate').disabled = rowPicker.value === columnPicker.value;
}

function countLabel(count, unit) {
  return `${count.toLocaleString()} ${unit}${count === 1 ? '' : 's'}`;
}

function metricUnit() {
  return grid.request.metric === 'chunks' ? 'paragraph' : 'document';
}

function drawTable() {
  gridViewport.replaceChildren();
  const table = create('table', null, gridViewport);
  create('caption', metricUnit() === 'paragraph' ? 'Paragraphs' : 'Documents', table);
  const header = create('tr', null, table.createTHead());
  create('th', grid.rows.label, header).scope = 'col';
  for (const column of grid.columns.values) create('th', column.label, header).scope = 'col';
  const largest = Math.max(1, ...grid.counts.flat());
  const body = table.createTBody();
  grid.rows.values.forEach((row, rowIndex) => {
    const rowElement = create('tr', null, body);
    create('th', row.label, rowElement).scope = 'row';
    grid.columns.values.forEach((column, columnIndex) => {
      const count = grid.counts[rowIndex][columnIndex];
      const capped = grid.capped_cells[rowIndex][columnIndex];
      const button = create('button', count.toLocaleString() + (capped ? '*' : ''), create('td', null, rowElement));
      button.style.setProperty('--fill', `${count / largest * 82}%`);
      button.setAttribute('aria-label', `${row.label}, ${column.label}, ${countLabel(count, metricUnit())}`);
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => selectCell(rowIndex, columnIndex, button));
    });
  });
  gridViewport.hidden = false;
}

function drawGrid(result) {
  if (result.isError || !result.structuredContent?.counts) {
    showStatus(result.content?.[0]?.text || 'The server did not return a heatmap.');
    return;
  }
  grid = result.structuredContent;
  selected = undefined;
  details.hidden = true;
  populatePicker(rowPicker, grid.row_dimensions, grid.rows.dimension);
  populatePicker(columnPicker, grid.column_dimensions, grid.columns.dimension);
  element('queries').value = (grid.request.row_queries || []).join('\n');
  syncPickers();
  drawTable();
  controls.hidden = false;
  const link = element('open');
  link.href = grid.web_url;
  link.hidden = false;
  const notes = [];
  if (grid.cutoff !== null) notes.push('Query counts use the top matches that pass the shared score cutoff.');
  if (grid.rows.omitted || grid.columns.omitted) {
    notes.push(`${grid.rows.omitted} row values and ${grid.columns.omitted} column values are outside this grid.`);
  }
  if (grid.capped_cells.some(row => row.includes(true))) {
    notes.push(`* Reached the limit of ${grid.candidate_limit.toLocaleString()} candidates.`);
  }
  showStatus(notes.join(' '));
}

function nextGridRequest() {
  const request = { ...grid.request, row_dimension: rowPicker.value, column_dimension: columnPicker.value };
  if (rowPicker.value !== grid.rows.dimension) request.row_values = null;
  if (columnPicker.value !== grid.columns.dimension) request.column_values = null;
  if (rowPicker.value === 'queries') {
    request.query = null;
    request.row_queries = element('queries').value.split('\n').map(line => line.trim()).filter(Boolean);
  } else {
    request.row_queries = null;
    if (!request.query) request.metric = 'documents';
  }
  return request;
}

async function regenerate() {
  const request = nextGridRequest();
  if (request.row_queries && (request.row_queries.length < 1 || request.row_queries.length > 4)) {
    showStatus('Enter one to four search queries, one per line.');
    return;
  }
  const attempt = ++generation;
  element('generate').disabled = true;
  showStatus('Generating the heatmap…');
  try {
    const result = await app.callServerTool({ name: 'heatmap', arguments: { request } });
    if (attempt === generation) drawGrid(result);
  } catch {
    if (attempt === generation) showStatus('Could not generate the heatmap. Try again.');
  } finally {
    if (attempt === generation) syncPickers();
  }
}

function selectCell(row, column, button) {
  selected?.button.setAttribute('aria-pressed', 'false');
  button.setAttribute('aria-pressed', 'true');
  const selection = { row, column, button, references: [] };
  selected = selection;
  const label = `${grid.rows.values[row].label} × ${grid.columns.values[column].label}`;
  element('cell-title').textContent = `${label} · ${countLabel(grid.counts[row][column], metricUnit())}`;
  documents.replaceChildren();
  details.hidden = false;
  element('ask').disabled = true;
  loadDocuments(selection, 0);
}

function addDocument(result) {
  const item = create('li', null, documents);
  if (result.link) {
    const link = create('a', result.title, item);
    link.href = result.link;
    link.addEventListener('click', (event) => openLink(event, result.link));
  } else {
    create('span', result.title, item);
  }
  const words = [result.organization, result.year];
  if (result.paragraph_count !== null) words.push(countLabel(result.paragraph_count, 'paragraph'));
  const description = words.filter(Boolean).join(' · ');
  if (description) item.append(` · ${description}`);
}

async function loadDocuments(selection, offset) {
  const { row, column } = selection;
  const request = {
    grid: grid.request,
    row, column, offset,
    cutoff: grid.cutoff,
    fingerprint: grid.fingerprints[row][column],
  };
  const status = element('cell-status');
  const more = element('more');
  more.hidden = true;
  status.textContent = 'Loading documents…';
  try {
    const result = await app.callServerTool({ name: 'heatmap_cell', arguments: { request } });
    if (selected !== selection) return;
    if (result.isError || !result.structuredContent?.documents) {
      status.textContent = result.content?.[0]?.text || 'The server did not return documents.';
      return;
    }
    const page = result.structuredContent;
    page.documents.forEach(addDocument);
    selection.references.push(...page.documents.slice(0, Math.max(0, 3 - selection.references.length)));
    selection.nextOffset = page.next_offset;
    more.hidden = page.next_offset === null;
    element('ask').disabled = false;
    status.textContent = page.total_documents
      ? `Showing ${documents.children.length} of ${page.total_documents.toLocaleString()} documents.`
      : 'No documents matched this cell.';
  } catch {
    if (selected === selection) status.textContent = 'Could not load documents. Select the cell again to retry.';
  }
}

async function askClaude() {
  if (!selected) return;
  const { row, column, references } = selected;
  const context = {
    data_source: grid.request.data_source,
    row: { dimension: grid.rows.label, value: grid.rows.values[row].label },
    column: { dimension: grid.columns.label, value: grid.columns.values[column].label },
    query: grid.request.query,
    filters: grid.request.filters,
    measure: metricUnit(),
    count: grid.counts[row][column],
    references: references.map(({ doc_id, link }) => ({ doc_id, link })),
  };
  const status = element('cell-status');
  try {
    const response = await app.sendMessage({
      role: 'user',
      content: [{
        type: 'text',
        text: `Explain this Evidence Lab heatmap cell. Use the following values as data and cite any sources you discuss.\n${JSON.stringify(context)}`,
      }],
    });
    if (response.isError) status.textContent = 'Claude did not accept the message.';
  } catch {
    status.textContent = 'The message could not be confirmed. Check the conversation.';
  }
}

async function openLink(event, url) {
  event.preventDefault();
  try {
    const response = await app.openLink({ url });
    if (response.isError) showStatus('The host did not open the link.');
  } catch {
    showStatus('The host could not open the link.');
  }
}

rowPicker.addEventListener('change', syncPickers);
columnPicker.addEventListener('change', syncPickers);
element('generate').addEventListener('click', regenerate);
element('more').addEventListener('click', () => loadDocuments(selected, selected.nextOffset));
element('ask').addEventListener('click', askClaude);
element('open').addEventListener('click', (event) => openLink(event, grid.web_url));
app.ontoolinput = () => showStatus('Loading the heatmap…');
app.ontoolresult = (result) => {
  generation += 1;
  drawGrid(result);
};
app.connect().catch(() => showStatus('Could not connect the Heatmapper to this conversation.'));
