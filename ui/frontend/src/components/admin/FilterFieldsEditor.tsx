import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import API_BASE_URL from '../../config';
import type { DataSourceConfigItem } from '../../App';

interface FilterFieldsEditorProps {
  datasourceKeys: string[];
  datasourcesConfig: Record<string, DataSourceConfigItem>;
  currentFilterFields?: Record<string, Record<string, string>>;
  onChange: (filterFields: Record<string, Record<string, string>>) => void;
}

interface SortableItemProps {
  id: string;
  label: string;
  onRemove: (id: string) => void;
  onLabelChange: (id: string, label: string) => void;
}

const SortableItem: React.FC<SortableItemProps> = ({ id, label, onRemove, onLabelChange }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className="filter-field-active">
      <span className="drag-handle" {...attributes} {...listeners}>
        &#x2630;
      </span>
      <span className="filter-field-key">{id}</span>
      <input
        type="text"
        className="filter-field-label-input"
        value={label}
        onChange={(e) => onLabelChange(id, e.target.value)}
        placeholder="Display label"
        title="Display label shown to users"
      />
      <button
        className="filter-field-remove"
        onClick={() => onRemove(id)}
        aria-label={`Remove ${id}`}
        title="Remove field"
      >
        &times;
      </button>
    </div>
  );
};

/** Fields that are internal/system and should not appear as filter choices. */
const HIDDEN_FIELDS = new Set([
  'is_duplicate',
  'doc_id',
]);

/** Prefixes stripped when humanizing a field key into a display label. */
const STRIP_PREFIXES = ['map_', 'src_', 'tag_', 'sys_'];

/** Derive a human-readable label from a payload field key. */
const humanize = (key: string): string => {
  let base = key;
  const prefix = STRIP_PREFIXES.find((p) => base.startsWith(p));
  if (prefix) base = base.slice(prefix.length);
  // Title-case with spaces
  return base
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
};

const FilterFieldsEditor: React.FC<FilterFieldsEditorProps> = ({
  datasourceKeys,
  datasourcesConfig,
  currentFilterFields,
  onChange,
}) => {
  const [selectedDatasource, setSelectedDatasource] = useState<string>(
    datasourceKeys[0] || ''
  );
  /** All indexed payload field names from Qdrant for the selected datasource. */
  const [payloadFields, setPayloadFields] = useState<string[]>([]);
  const [loadingFields, setLoadingFields] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Fetch payload fields from Qdrant when datasource changes
  useEffect(() => {
    if (!selectedDatasource) return;
    let cancelled = false;
    setLoadingFields(true);
    axios
      .get<{ fields: string[] }>(
        `${API_BASE_URL}/config/datasources/${selectedDatasource}/payload-fields`
      )
      .then((resp) => {
        if (!cancelled) {
          setPayloadFields(resp.data.fields || []);
          setLoadingFields(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPayloadFields([]);
          setLoadingFields(false);
        }
      });
    return () => { cancelled = true; };
  }, [selectedDatasource]);

  // Get default filter fields for the selected datasource (from config)
  const defaultFields = useMemo(() => {
    if (!selectedDatasource) return {};
    const dsConfig = datasourcesConfig[selectedDatasource];
    return dsConfig?.default_filter_fields || {};
  }, [selectedDatasource, datasourcesConfig]);

  // Get currently active fields for the selected datasource.
  // When no override exists, show the default_filter_fields as the starting set.
  const hasOverride = selectedDatasource in (currentFilterFields || {});

  const activeFields: Record<string, string> = useMemo(() => {
    if (!selectedDatasource) return {};
    if (hasOverride) return currentFilterFields![selectedDatasource];
    return defaultFields;
  }, [selectedDatasource, currentFilterFields, hasOverride, defaultFields]);

  // Ordered list of active field keys
  const activeFieldKeys = useMemo(() => Object.keys(activeFields), [activeFields]);

  // Available fields = payload fields (+ defaults) not already active, minus hidden
  const availableFields = useMemo(() => {
    const allKeys = new Set([
      ...payloadFields,
      ...Object.keys(defaultFields),
    ]);
    const result: Array<{ key: string; label: string }> = [];
    for (const key of Array.from(allKeys).sort()) {
      if (activeFields[key] || HIDDEN_FIELDS.has(key)) continue;
      // Prefer label from default_filter_fields, otherwise humanize
      const label = defaultFields[key] || humanize(key);
      result.push({ key, label });
    }
    return result;
  }, [payloadFields, defaultFields, activeFields]);

  const updateFields = useCallback(
    (dsKey: string, fields: Record<string, string>) => {
      const next = { ...(currentFilterFields || {}) };
      if (Object.keys(fields).length === 0) {
        delete next[dsKey];
      } else {
        next[dsKey] = fields;
      }
      onChange(next);
    },
    [currentFilterFields, onChange]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = activeFieldKeys.indexOf(active.id as string);
      const newIndex = activeFieldKeys.indexOf(over.id as string);
      const reorderedKeys = arrayMove(activeFieldKeys, oldIndex, newIndex);

      const newFields: Record<string, string> = {};
      for (const key of reorderedKeys) {
        newFields[key] = activeFields[key];
      }
      updateFields(selectedDatasource, newFields);
    },
    [activeFieldKeys, activeFields, selectedDatasource, updateFields]
  );

  const handleAdd = useCallback(
    (key: string) => {
      const label = defaultFields[key] || humanize(key);
      const newFields = { ...activeFields, [key]: label };
      updateFields(selectedDatasource, newFields);
    },
    [activeFields, defaultFields, selectedDatasource, updateFields]
  );

  const handleRemove = useCallback(
    (key: string) => {
      const newFields = { ...activeFields };
      delete newFields[key];
      updateFields(selectedDatasource, newFields);
    },
    [activeFields, selectedDatasource, updateFields]
  );

  const handleLabelChange = useCallback(
    (key: string, label: string) => {
      const newFields = { ...activeFields, [key]: label };
      updateFields(selectedDatasource, newFields);
    },
    [activeFields, selectedDatasource, updateFields]
  );

  const handleClearOverride = useCallback(() => {
    const next = { ...(currentFilterFields || {}) };
    delete next[selectedDatasource];
    onChange(next);
  }, [currentFilterFields, selectedDatasource, onChange]);

  if (datasourceKeys.length === 0) {
    return <p className="text-muted">No datasources configured for this group.</p>;
  }

  return (
    <div className="filter-fields-editor">
      {/* Datasource selector */}
      {datasourceKeys.length > 1 && (
        <div className="filter-fields-datasource-select">
          <label className="search-settings-label">Datasource</label>
          <select
            value={selectedDatasource}
            onChange={(e) => setSelectedDatasource(e.target.value)}
            className="filter-fields-select"
          >
            {datasourceKeys.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
        </div>
      )}

      {!hasOverride && (
        <p className="text-muted" style={{ fontSize: '0.85em', marginBottom: '8px' }}>
          Showing default filter fields. Drag, add, or remove to create a custom override.
        </p>
      )}

      {/* Active fields (sortable) */}
      <div className="filter-fields-section">
        <label className="search-settings-label">Active Filters (drag to reorder)</label>
        {activeFieldKeys.length === 0 ? (
          <p className="text-muted" style={{ fontSize: '0.85em' }}>
            No filters selected. Add fields below.
          </p>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={activeFieldKeys}
              strategy={verticalListSortingStrategy}
            >
              <div className="filter-fields-list">
                {activeFieldKeys.map((key) => (
                  <SortableItem
                    key={key}
                    id={key}
                    label={activeFields[key]}
                    onRemove={handleRemove}
                    onLabelChange={handleLabelChange}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}
      </div>

      {/* Available fields */}
      <div className="filter-fields-section">
        <label className="search-settings-label">Available Fields</label>
        {loadingFields ? (
          <p className="text-muted" style={{ fontSize: '0.85em' }}>
            Loading fields…
          </p>
        ) : availableFields.length === 0 ? (
          <p className="text-muted" style={{ fontSize: '0.85em' }}>
            All fields are active.
          </p>
        ) : (
          <div className="filter-fields-list">
            {availableFields.map(({ key, label }) => (
              <div key={key} className="filter-field-available">
                <span className="filter-field-key-available">{key}</span>
                <span className="filter-field-label">{label}</span>
                <button
                  className="btn-sm filter-field-add"
                  onClick={() => handleAdd(key)}
                  title={`Add ${key}`}
                >
                  + Add
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Reset to defaults */}
      {hasOverride && (
        <button
          className="btn-sm btn-danger"
          onClick={handleClearOverride}
          style={{ marginTop: '8px' }}
        >
          Reset to Defaults
        </button>
      )}
    </div>
  );
};

export default FilterFieldsEditor;
