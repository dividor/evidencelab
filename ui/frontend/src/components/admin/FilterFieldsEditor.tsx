import React, { useCallback, useMemo, useState } from 'react';
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
}

const SortableItem: React.FC<SortableItemProps> = ({ id, label, onRemove }) => {
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
      <span className="filter-field-label">{label}</span>
      <button
        className="filter-field-remove"
        onClick={() => onRemove(id)}
        aria-label={`Remove ${label}`}
        title="Remove field"
      >
        &times;
      </button>
    </div>
  );
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

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Get default filter fields for the selected datasource
  const defaultFields = useMemo(() => {
    if (!selectedDatasource) return {};
    const dsConfig = datasourcesConfig[selectedDatasource];
    return dsConfig?.default_filter_fields || {};
  }, [selectedDatasource, datasourcesConfig]);

  // Get currently active fields for the selected datasource
  const activeFields: Record<string, string> = useMemo(() => {
    if (!selectedDatasource) return {};
    return currentFilterFields?.[selectedDatasource] || {};
  }, [selectedDatasource, currentFilterFields]);

  const hasOverride = selectedDatasource in (currentFilterFields || {});

  // Ordered list of active field keys
  const activeFieldKeys = useMemo(() => Object.keys(activeFields), [activeFields]);

  // Available fields = default fields not in active
  const availableFields = useMemo(() => {
    const result: Array<{ key: string; label: string }> = [];
    for (const [key, label] of Object.entries(defaultFields)) {
      if (!activeFields[key]) {
        result.push({ key, label });
      }
    }
    return result;
  }, [defaultFields, activeFields]);

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
      const label = defaultFields[key];
      if (!label) return;
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

  const handleUseDefaults = useCallback(() => {
    updateFields(selectedDatasource, defaultFields);
  }, [defaultFields, selectedDatasource, updateFields]);

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

      {!hasOverride ? (
        <div className="filter-fields-default-notice">
          <p>Using default filter fields for this datasource.</p>
          <button className="btn-sm" onClick={handleUseDefaults}>
            Customize Fields
          </button>
        </div>
      ) : (
        <>
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
                      />
                    ))}
                  </div>
                </SortableContext>
              </DndContext>
            )}
          </div>

          {/* Available fields */}
          {availableFields.length > 0 && (
            <div className="filter-fields-section">
              <label className="search-settings-label">Available Fields</label>
              <div className="filter-fields-list">
                {availableFields.map(({ key, label }) => (
                  <div key={key} className="filter-field-available">
                    <span className="filter-field-label">{label}</span>
                    <button
                      className="btn-sm filter-field-add"
                      onClick={() => handleAdd(key)}
                      title={`Add ${label}`}
                    >
                      + Add
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Reset to defaults */}
          <button
            className="btn-sm btn-danger"
            onClick={handleClearOverride}
            style={{ marginTop: '8px' }}
          >
            Reset to Defaults
          </button>
        </>
      )}
    </div>
  );
};

export default FilterFieldsEditor;
