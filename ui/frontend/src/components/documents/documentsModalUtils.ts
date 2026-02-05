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
      const flattened = Object.entries(rawMetaItem.value).map(([k, v]) => ({
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

const processSysItems = (items: any[], specialEntries: [string, any][], docIdValue?: any, fileIdValue?: any) => {
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
      items = processSysItems(items, specialEntries, docIdValue, fileIdValue);
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
