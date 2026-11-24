// Live network status from the native bridge (+ backend /network/status when
// in backend mode). Polls every 10s and listens for NetworkChanged events.
import {useCallback, useEffect, useRef, useState} from 'react';
import {NetworkInfo, NetworkStatus, Settings} from '../types';
import {addNetworkChangedListener, getNetworkInfo} from '../services/native';
import {getNetworkStatus} from '../services/api';
import {loadSettings} from '../utils/storage';

const POLL_INTERVAL_MS = 10000;

export function useNetworkStatus() {
  const [networkInfo, setNetworkInfo] = useState<NetworkInfo | null>(null);
  const [backendStatus, setBackendStatus] = useState<NetworkStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const info = await getNetworkInfo();
      if (mounted.current) {
        setNetworkInfo(info);
        setError(null);
      }
      const s = await loadSettings();
      if (mounted.current) {
        setSettings(s);
      }
      if (s.mode === 'backend') {
        const result = await getNetworkStatus();
        if (mounted.current) {
          if (result.success && result.data) {
            setBackendStatus(result.data);
          } else {
            // Backend unreachable is reported, not hidden: keep native info
            // and record the backend error.
            setBackendStatus(null);
            setError(result.error ?? 'Backend network status unavailable.');
          }
        }
      } else if (mounted.current) {
        setBackendStatus(null);
      }
    } catch (err) {
      if (mounted.current) {
        setError(err instanceof Error ? err.message : 'Network info unavailable.');
      }
    } finally {
      if (mounted.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    let subscription: {remove(): void} | null = null;
    try {
      subscription = addNetworkChangedListener(event => {
        setNetworkInfo((prev: NetworkInfo | null) =>
          prev
            ? {...prev, connected: event.connected, ssid: event.ssid, ipAddress: event.ipAddress}
            : prev,
        );
        void refresh();
      });
    } catch {
      // Native module absent: polling via refresh() already surfaces the error.
      subscription = null;
    }
    return () => {
      mounted.current = false;
      clearInterval(timer);
      subscription?.remove();
    };
  }, [refresh]);

  return {networkInfo, backendStatus, settings, loading, error, refresh};
}
