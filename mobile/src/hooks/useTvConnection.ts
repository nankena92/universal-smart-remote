// Shared TV-connection state for screens.
import {useCallback, useEffect, useState} from 'react';
import {PairedTv, RemoteKey} from '../types';
import {remoteService} from '../services/remote';

export function useTvConnection() {
  const [connectedTv, setConnectedTvState] = useState<PairedTv | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const tv = await remoteService.restoreConnectedTv();
      setConnectedTvState(tv ?? remoteService.getConnectedTv());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the connected TV.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const sendKey = useCallback(async (key: RemoteKey): Promise<boolean> => {
    setSending(true);
    setError(null);
    try {
      await remoteService.sendKey(key);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to send ${key}.`);
      return false;
    } finally {
      setSending(false);
    }
  }, []);

  const disconnect = useCallback(async (): Promise<boolean> => {
    try {
      await remoteService.disconnectTv();
      setConnectedTvState(null);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disconnect.');
      return false;
    }
  }, []);

  const setConnectedTv = useCallback(async (tv: PairedTv | null) => {
    await remoteService.setConnectedTv(tv);
    setConnectedTvState(tv);
  }, []);

  return {
    connectedTv,
    loading,
    error,
    sending,
    setError,
    refresh,
    sendKey,
    disconnect,
    setConnectedTv,
  };
}
