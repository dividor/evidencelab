import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import type { BriefCheckRun, BriefFactCheckRead } from '../../types/testing';
import { getBriefFactCheck, readFactCheckRun, startFactCheck, stopFactCheck } from './briefFactCheckApi';

export function useBriefCheckRun(briefId: string | null, revision: number, modelCombo?: string | null) {
  const [result, setResult] = useState<BriefFactCheckRead | null>(null);
  const [run, setRun] = useState<BriefCheckRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [active, setActive] = useState(false);
  const currentBrief = useRef(briefId);
  currentBrief.current = briefId;

  useEffect(() => {
    setResult(null);
    setRun(null);
    setActive(false);
    setNotice('');
    setBusy(false);
  }, [briefId]);

  useEffect(() => {
    if (!briefId) return;
    let current = true;
    getBriefFactCheck(briefId).then(read => {
      if (!current) return;
      setResult(read);
      if (read.active_run) setRun(read.active_run);
      if (!read.marks.length) setActive(false);
    }).catch(err => {
      if (!current) return;
      setResult(null);
      if (!(axios.isAxiosError(err) && err.response?.status === 404)) {
        setNotice('The fact check could not be loaded.');
      }
    });
    return () => { current = false; };
  }, [briefId, revision]);

  const runId = run?.id;
  useEffect(() => {
    if (!briefId || !runId) return;
    let current = true;
    let timer: number;
    async function poll(id: string, check: string) {
      try {
        const next = await readFactCheckRun(id, check);
        if (!current) return;
        if (next.status === 'completed' || next.status === 'failed') {
          const read = await getBriefFactCheck(id);
          if (!current) return;
          setResult(read);
          setRun(null);
          if (next.status === 'completed' && read.check?.id === next.id && read.marks.length) {
            setActive(true);
            setNotice('');
          } else {
            setNotice(next.stopped ? 'Fact check stopped.' : next.status === 'failed'
              ? 'The fact check failed. You can try again.' : 'The check finished with no results for this version.');
          }
          return;
        }
        setRun(next);
        setNotice('');
      } catch {
        if (!current) return;
        setNotice('Could not update fact check progress. Reconnecting…');
      }
      timer = window.setTimeout(() => poll(id, check), 2000);
    }
    void poll(briefId, runId);
    return () => { current = false; window.clearTimeout(timer); };
  }, [briefId, runId]);

  async function changeRun(request: (id: string) => Promise<BriefCheckRun>) {
    if (!briefId || busy) return;
    setBusy(true);
    setNotice('');
    try {
      const next = await request(briefId);
      if (currentBrief.current === briefId) setRun(next);
    } catch (err) {
      if (currentBrief.current === briefId) {
        const detail = axios.isAxiosError(err) && err.response?.data?.detail;
        setNotice(typeof detail === 'string' ? detail : 'The fact check request failed. Please try again.');
      }
    } finally {
      if (currentBrief.current === briefId) setBusy(false);
    }
  }

  return { result, run, active, setActive, notice, busy,
    disabledReason: !briefId ? 'Save this brief before checking facts.' : !result ? 'Fact check status is unavailable.' : result.start_disabled_reason,
    start: () => changeRun(id => startFactCheck(id, modelCombo)),
    stop: () => { if (run) void changeRun(id => stopFactCheck(id, run.id)); },
  };
}
