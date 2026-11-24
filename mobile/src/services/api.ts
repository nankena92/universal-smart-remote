// REST client for the FastAPI backend (CONTRACTS.md §2).
// Base URL + API key come from Settings (AsyncStorage); default http://192.168.1.100:8000.
// Every function returns {success, data?, error?} and never claims success on a
// failed HTTP call. Auth: X-API-Key header when a key is configured.
import {
  ApiResult,
  ConnectionStatus,
  DiscoveredTv,
  HealthStatus,
  NetworkStatus,
  PairedTv,
  RemoteKey,
  Settings,
  StreamingAppId,
} from '../types';
import {loadSettings} from '../utils/storage';

const REQUEST_TIMEOUT_MS = 10000;

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {...init, signal: controller.signal});
  } finally {
    clearTimeout(timer);
  }
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === 'AbortError') {
      return 'Request timed out. Check that the backend is reachable on this Wi-Fi network.';
    }
    return err.message;
  }
  return 'Network request failed.';
}

async function parseBody(res: Response): Promise<Record<string, unknown>> {
  const text = await res.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return {raw: text};
  }
}

export async function getBackendSettings(): Promise<Settings> {
  return loadSettings();
}

export function normaliseBaseUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, '');
}

async function request<T>(
  path: string,
  options: {method?: string; body?: unknown; timeoutMs?: number} = {},
): Promise<ApiResult<T>> {
  const settings = await loadSettings();
  const baseUrl = normaliseBaseUrl(settings.backendUrl);
  const headers: Record<string, string> = {'Content-Type': 'application/json'};
  if (settings.apiKey) {
    headers['X-API-Key'] = settings.apiKey;
  }
  let res: Response;
  try {
    res = await fetchWithTimeout(
      `${baseUrl}${path}`,
      {
        method: options.method ?? 'GET',
        headers,
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      },
      options.timeoutMs,
    );
  } catch (err) {
    return {success: false, error: errorMessage(err)};
  }
  const body = await parseBody(res);
  if (!res.ok) {
    const message =
      typeof body.error === 'string' && body.error
        ? body.error
        : `Backend returned HTTP ${res.status}.`;
    return {success: false, error: message};
  }
  if (body.success === false) {
    return {
      success: false,
      error:
        typeof body.error === 'string' && body.error
          ? body.error
          : 'Backend reported failure.',
    };
  }
  // Endpoints return either {success, ...data} or {success, data}. Unwrap both.
  const data = ('data' in body ? body.data : body) as T;
  return {success: true, data};
}

// --- Health / network ---

export async function checkHealth(): Promise<ApiResult<HealthStatus>> {
  return request<HealthStatus>('/health');
}

export async function getNetworkStatus(): Promise<ApiResult<NetworkStatus>> {
  return request<NetworkStatus>('/network/status');
}

export async function getConnectionStatus(): Promise<ApiResult<ConnectionStatus>> {
  return request<ConnectionStatus>('/devices/connection-status');
}

// --- Devices ---

export async function discoverDevices(): Promise<ApiResult<DiscoveredTv[]>> {
  // Discovery on the backend can take a while (SSDP/mDNS sweep).
  const result = await request<DiscoveredTv[]>('/devices/discover', {
    timeoutMs: 30000,
  });
  if (!result.success || !result.data) {
    return result;
  }
  const list = Array.isArray(result.data) ? result.data : [];
  return {success: true, data: list};
}

export async function listDevices(): Promise<ApiResult<PairedTv[]>> {
  const result = await request<PairedTv[]>('/devices');
  if (!result.success || !result.data) {
    return result;
  }
  return {success: true, data: Array.isArray(result.data) ? result.data : []};
}

export async function connectDevice(
  device: {
    device_id?: string;
    ip?: string;
    brand?: string;
    name?: string;
    model?: string;
    port?: number;
    mac?: string;
  },
): Promise<ApiResult<ConnectionStatus>> {
  return request<ConnectionStatus>('/devices/connect', {
    method: 'POST',
    body: device,
  });
}

export async function pairDevice(
  deviceId: string,
  pin?: string,
): Promise<ApiResult<ConnectionStatus>> {
  return request<ConnectionStatus>('/devices/pair', {
    method: 'POST',
    body: pin ? {device_id: deviceId, pin} : {device_id: deviceId},
  });
}

export async function disconnectDevice(
  deviceId: string,
): Promise<ApiResult<{disconnected: boolean}>> {
  // CONTRACTS.md §2: DELETE /devices/disconnect {device_id}
  return request<{disconnected: boolean}>('/devices/disconnect', {
    method: 'DELETE',
    body: {device_id: deviceId},
  });
}

// --- Remote keys ---

const KEY_ENDPOINTS: Record<RemoteKey, string> = {
  up: '/remote/up',
  down: '/remote/down',
  left: '/remote/left',
  right: '/remote/right',
  ok: '/remote/ok',
  back: '/remote/back',
  home: '/remote/home',
  menu: '/remote/menu',
  power: '/remote/power',
  'volume-up': '/remote/volume-up',
  'volume-down': '/remote/volume-down',
  mute: '/remote/mute',
  'channel-up': '/remote/channel-up',
  'channel-down': '/remote/channel-down',
  play: '/remote/play',
  pause: '/remote/pause',
  stop: '/remote/stop',
  rewind: '/remote/rewind',
  'fast-forward': '/remote/fast-forward',
};

export async function sendRemoteKey(
  key: RemoteKey,
  deviceId?: string,
): Promise<ApiResult<Record<string, unknown>>> {
  const path = KEY_ENDPOINTS[key];
  if (!path) {
    return {success: false, error: `Unknown remote key: ${key}`};
  }
  return request<Record<string, unknown>>(path, {
    method: 'POST',
    body: deviceId ? {device_id: deviceId} : {},
  });
}

export async function launchApp(
  app: StreamingAppId,
  deviceId?: string,
): Promise<ApiResult<Record<string, unknown>>> {
  return request<Record<string, unknown>>('/remote/launch-app', {
    method: 'POST',
    body: deviceId ? {app, device_id: deviceId} : {app},
  });
}
