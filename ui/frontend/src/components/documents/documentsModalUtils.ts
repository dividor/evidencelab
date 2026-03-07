export const buildSummaryDisplayText = (summary: string): string => {
  let displayText = summary;


  displayText = displayText.replace(
    /^\s*(?:[-*]|\u2022|\u2023|\u25E6|\u2043|\u2219)\s+(?:\*\*)?(Summary|Context|Findings|Recommendations|Topics|Core Concepts and Terms|Methodological Patterns)(?:\*\*)?\s*:/gmi,
    '$1:'
  );

  displayText = displayText.replace(
    /^\s*(?:\*\*)?(Summary|Context|Findings|Recommendations|Topics|Core Concepts and Terms|Methodological Patterns)(?:\*\*)?\s*:/gmi,
    '$1:'
  );

  return displayText.replace(
    /^\s*(Summary|Context|Findings|Recommendations|Topics|Core Concepts and Terms|Methodological Patterns)\s*:\s*\*\*/gmi,
    '$1: '
  );
};

const processSrcItems = (items: any[], coreKeys: string[]) => {
  const coreFieldSet = new Set(coreKeys);
  let processedItems = items.filter((item) => !coreFieldSet.has(item.displayKey));

  const rawMetaIdx = processedItems.findIndex((item) => item.displayKey === 'doc_raw_metadata');
  if (rawMetaIdx !== -1) {
    const rawMetaItem = processedItems[rawMetaIdx];
    processedItems.splice(rawMetaIdx, 1);
    if (
      rawMetaItem.value &&
      typeof rawMetaItem.value === 'object' &&
      !Array.isArray(rawMetaItem.value)
    ) {
      // Collect existing displayKeys to avoid duplicates when flattening raw metadata.
      // The backend may already unpack src_doc_raw_metadata into individual src_* fields,
      // so we skip raw metadata keys that are already present.
      const existingDisplayKeys = new Set(processedItems.map((item) => item.displayKey));
      const flattened = Object.entries(rawMetaItem.value)
        .filter(([k]) => !existingDisplayKeys.has(k.replace(/^src_/, '')))
        .map(([k, v]) => ({
          key: `raw_${k}`,
          displayKey: k.replace(/^src_/, ''),
          value: v,
        }));
      processedItems = [...processedItems, ...flattened];
    }
  }
  return processedItems.sort((a, b) => a.displayKey.localeCompare(b.displayKey));
};

const processMapItems = (items: any[], coreKeys: string[], metadata: Record<string, any>) => {
  const existing = new Set(items.map((item) => item.displayKey));
  const missingCore = coreKeys
    .filter((key) => !existing.has(key))
    .map((key) => ({
      key: `core_${key}`,
      displayKey: key,
      value: metadata?.[key] ?? '-',
    }));
  return [...items, ...missingCore].sort((a, b) => a.displayKey.localeCompare(b.displayKey));
};

const processSysItems = (items: any[], specialEntries: [string, any][], docIdValue?: any, fileIdValue?: any, chunkIdValue?: any) => {
  let processedItems = [...items];

  if (specialEntries.length > 0) {
    const existingDisplayKeys = new Set(processedItems.map((item) => item.displayKey));
    const specialItems = specialEntries
      .filter(([key]) => !existingDisplayKeys.has(key))
      .map(([key, value]) => ({
        key,
        displayKey: key,
        value,
      }));
    processedItems = [...specialItems, ...processedItems];
  }

  if (chunkIdValue !== undefined) {
    const hasChunkIdItem = processedItems.some((item) => item.displayKey === 'chunk_id');
    if (!hasChunkIdItem) {
      processedItems = [{ key: 'chunk_id', displayKey: 'chunk_id', value: chunkIdValue }, ...processedItems];
    }
  }

  if (docIdValue !== undefined) {
    const hasDocIdItem = processedItems.some((item) => item.displayKey === 'doc_id');
    if (!hasDocIdItem) {
      processedItems = [{ key: 'doc_id', displayKey: 'doc_id', value: docIdValue }, ...processedItems];
    }
  }

  if (fileIdValue !== undefined) {
    const hasFileIdItem = processedItems.some((item) => item.displayKey === 'file_id');
    if (!hasFileIdItem) {
      processedItems = [{ key: 'file_id', displayKey: 'file_id', value: fileIdValue }, ...processedItems];
    }
  }
  return processedItems;
};

export const buildMetadataSections = (metadata: Record<string, any>) => {
  const excludedKeys = new Set([
    'status',
    'metadata_checksum',
    'word_count',
    'file_checksum',
    'filepath',
    'parsed_folder',
    'stages',
    'pipeline_elapsed_seconds',
    'summarization_method',
    'user_edited_section_types',
    'sys_data',
  ]);
  const sections = [
    { label: 'Core Fields', prefix: 'map_' },
    { label: 'Source System Fields', prefix: 'src_' },
    { label: 'System Fields', prefix: 'sys_' },
  ];
  const coreKeys = [
    'organization',
    'document_type',
    'published_year',
    'country',
    'region',
    'theme',
    'language',
    'title',
    'pdf_url',
    'report_url',
    'filepath',
  ];
  const entries = Object.entries(metadata).filter(
    ([key]) =>
      !excludedKeys.has(key) &&
      (key.startsWith('src_') || key.startsWith('map_') || key.startsWith('sys_'))
  );
  const specialKeys = ['full_summary', 'toc', 'toc_classified'];
  const specialEntries = specialKeys
    .filter((key) => Object.prototype.hasOwnProperty.call(metadata, key))
    .map((key) => [key, metadata[key]] as [string, any]);

  const hasFileId = Object.prototype.hasOwnProperty.call(metadata, 'file_id');
  const hasId = Object.prototype.hasOwnProperty.call(metadata, 'id');
  const fileIdValue = hasFileId ? metadata.file_id : hasId ? metadata.id : undefined;
  const docIdValue = Object.prototype.hasOwnProperty.call(metadata, 'doc_id')
    ? metadata.doc_id
    : undefined;
  const chunkIdValue = Object.prototype.hasOwnProperty.call(metadata, 'chunk_id')
    ? metadata.chunk_id
    : undefined;

  return sections.map((section) => {
    let items = entries
      .filter(([key]) => key.startsWith(section.prefix))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => ({
        key,
        displayKey: key.slice(section.prefix.length),
        value,
      }));

    if (section.prefix === 'src_') {
      items = processSrcItems(items, coreKeys);
    }

    if (section.prefix === 'map_') {
      items = processMapItems(items, coreKeys, metadata);
    }

    if (section.prefix === 'sys_') {
      items = processSysItems(items, specialEntries, docIdValue, fileIdValue, chunkIdValue);
    }

    return { ...section, items };
  });
};

export const buildTimelineStages = (stages: Record<string, any>) => {
  const stageOrder = ['download', 'parse', 'summarize', 'tag', 'index'];
  const stageLabels: Record<string, string> = {
    download: 'Downloaded',
    parse: 'Parsed',
    summarize: 'Summarized',
    tag: 'Tagged',
    index: 'Indexed',
  };

  return stageOrder.map((stageName) => {
    const stage = stages[stageName];
    const isCompleted = stage !== undefined;
    const isSuccess = stage?.success === true;
    const isFailed = stage?.success === false;
    const isPending = !isCompleted;

    return {
      stageName,
      label: stageLabels[stageName],
      stage,
      isSuccess,
      isFailed,
      isPending,
    };
  });
};

export const getLastUpdatedTimestamp = (stages: Record<string, any>): string => {
  if (!stages || typeof stages !== 'object') {
    return '';
  }

  let latestTimestamp = '';
  let latestEpoch = Number.NEGATIVE_INFINITY;

  Object.values(stages).forEach((stage) => {
    const timestamp = stage?.at;
    if (!timestamp) {
      return;
    }
    const epoch = Date.parse(timestamp);
    if (Number.isNaN(epoch)) {
      return;
    }
    if (epoch > latestEpoch) {
      latestEpoch = epoch;
      latestTimestamp = timestamp;
    }
  });

  return latestTimestamp;
};

export const formatTimestamp = (isoString: string): string => {
  if (!isoString) {
    return '';
  }
  return new Date(isoString).toLocaleString();
};

/**
 * For a given core field name (e.g. "organization"), find the actual metadata key
 * by trying exact match, then map_, src_, sys_, tag_ prefixes.
 * For already-prefixed keys (e.g. "src_geographic_scope"), exact match hits first.
 */
const resolveMetadataKey = (
  metadata: Record<string, any>,
  coreField: string,
): string | null => {
  // Exact match first (handles already-prefixed keys like src_geographic_scope)
  if (Object.prototype.hasOwnProperty.call(metadata, coreField)) {
    return coreField;
  }
  // Try standard prefixes
  const prefixes = ['map_', 'src_', 'sys_', 'tag_'];
  for (const prefix of prefixes) {
    const prefixed = `${prefix}${coreField}`;
    if (Object.prototype.hasOwnProperty.call(metadata, prefixed)) {
      return prefixed;
    }
  }
  return null;
};

/**
 * Resolve configured panel fields from doc metadata.
 * Returns items in config order with display labels from panelFields.
 * `configKey` is the original key from panelFields (e.g. "full_summary"),
 * `key` is the resolved metadata key (e.g. "sys_full_summary").
 */
export const resolveConfiguredFields = (
  metadata: Record<string, any>,
  panelFields: Record<string, string>,
): Array<{ key: string; configKey: string; displayKey: string; value: any }> => {
  const items: Array<{ key: string; configKey: string; displayKey: string; value: any }> = [];
  for (const [coreField, displayLabel] of Object.entries(panelFields)) {
    const resolvedKey = resolveMetadataKey(metadata, coreField);
    if (resolvedKey !== null) {
      const value = metadata[resolvedKey];
      if (value !== null && value !== undefined && value !== '') {
        items.push({
          key: resolvedKey,
          configKey: coreField,
          displayKey: displayLabel,
          value,
        });
      }
    }
  }
  return items;
};

/**
 * Get the set of all raw metadata keys that are covered by configured panel fields.
 * Used to filter these keys out of the "System Information" section.
 */
export const getConfiguredFieldKeys = (
  metadata: Record<string, any>,
  panelFields: Record<string, string>,
): Set<string> => {
  const keys = new Set<string>();
  for (const coreField of Object.keys(panelFields)) {
    const resolvedKey = resolveMetadataKey(metadata, coreField);
    if (resolvedKey !== null) {
      keys.add(resolvedKey);
    }
  }
  return keys;
};
