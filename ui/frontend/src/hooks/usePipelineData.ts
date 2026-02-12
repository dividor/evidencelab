import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';

interface StatsData {
  total_documents: number;
  indexed_documents: number;
  total_agencies: number;
  status_breakdown: Record<string, number>;
}

interface SankeyData {
  nodes: string[];
  node_colors: string[];
  links: {
    source: number[];
    target: number[];
    value: number[];
    color: string[];
  };
  annotations: {
    num_orgs: number;
    total_records: number;
    layer2_count: number;
    layer3_count: number;
    layer4_count: number;
    layer5_count?: number;
    layer6_count?: number;
  };
}

interface TimelineData {
  histogram: { x: string[]; y: number[] };
  phase_distribution: {
    x: string[];
    Parsing: number[];
    Summarizing: number[];
    Tagging: number[];
    Indexing: number[];
  };
  pages_histogram: { x: string[]; y: number[] };
  errors_histogram: {
    x: string[];
    "Parse Failed": number[];
    "Summarization Failed": number[];
    "Indexing Failed": number[];
  };
}

interface PipelineDataState {
  stats: StatsData | null;
  sankey: SankeyData | null;
  timeline: TimelineData | null;
  dataSource: string | null;
}

let pipelineDataCache: PipelineDataState | null = null;
let pipelineDataPromise: Promise<PipelineDataState> | null = null;

const fetchPipelineData = async (dataSource: string): Promise<PipelineDataState> => {
  const [statsRes, sankeyRes, timelineRes] = await Promise.all([
    axios.get(`${API_BASE_URL}/stats?data_source=${dataSource}`),
    axios.get(`${API_BASE_URL}/stats/sankey?data_source=${dataSource}`),
    axios.get(`${API_BASE_URL}/stats/timeline?data_source=${dataSource}`)
  ]);

  return {
    stats: statsRes.data as StatsData,
    sankey: sankeyRes.data as SankeyData,
    timeline: timelineRes.data as TimelineData,
    dataSource
  };
};

const getCachedData = (dataSource: string) => {
  if (!pipelineDataCache) {
    return null;
  }
  return pipelineDataCache.dataSource === dataSource ? pipelineDataCache : null;
};

const requestPipelineData = async (dataSource: string) => {
  const cached = getCachedData(dataSource);
  if (cached) {
    return cached;
  }

  if (pipelineDataCache && pipelineDataCache.dataSource !== dataSource) {
    pipelineDataCache = null;
    pipelineDataPromise = null;
  }

  if (!pipelineDataPromise) {
    pipelineDataPromise = fetchPipelineData(dataSource)
      .then((data) => {
        pipelineDataCache = data;
        return data;
      })
      .finally(() => {
        pipelineDataPromise = null;
      });
  }

  return pipelineDataPromise;
};

export const usePipelineData = (dataSource: string) => {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [sankeyData, setSankeyData] = useState<SankeyData | null>(null);
  const [timelineData, setTimelineData] = useState<TimelineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await requestPipelineData(dataSource);
      setStats(data.stats);
      setSankeyData(data.sankey);
      setTimelineData(data.timeline);
    } catch (err) {
      console.error('Error loading data:', err);
      setError('Failed to load statistics. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  }, [dataSource]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return {
    stats,
    sankeyData,
    timelineData,
    loading,
    error,
    reload: loadData
  };
};
