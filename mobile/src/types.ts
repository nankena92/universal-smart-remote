// Shared types for the Universal Smart TV Remote app.
// Mirrors CONTRACTS.md §1-§2 (brands, keys, streaming apps) and §3 (bridge types).

export type Brand =
  | 'samsung'
  | 'lg'
  | 'sony'
  | 'androidtv'
  | 'googletv'
  | 'tcl'
  | 'roku'
  | 'firetv'
  | 'mock'
  | 'unknown';

export type RemoteKey =
  | 'up'
  | 'down'
  | 'left'
  | 'right'
  | 'ok'
  | 'back'
  | 'home'
  | 'menu'
  | 'power'
  | 'volume-up'
  | 'volume-down'
  | 'mute'
  | 'channel-up'
  | 'channel-down'
  | 'play'
  | 'pause'
  | 'stop'
  | 'rewind'
  | 'fast-forward';

export type StreamingAppId = 'netflix' | 'prime' | 'youtube' | 'disney';

export type ConnectionMode = 'backend' | 'direct';

export interface DiscoveredTv {
  id: string;
  name: string;
  brand: string;
  model: string;
  ip: string;
  port: number;
  mac: string;
  source: 'ssdp' | 'bonjour' | 'manual';
  paired?: boolean;
}

export interface PairedTv extends DiscoveredTv {
  paired: boolean;
  pairingToken?: string;
  lastConnected?: string;
}

export interface NetworkInfo {
  connected: boolean;
  isWifi: boolean;
  isCellular: boolean;
  ssid: string | null;
  bssid: string | null;
  ipAddress: string | null;
  subnetMask: string | null;
  gateway: string | null;
}

export interface NetworkChangedEvent {
  connected: boolean;
  ssid: string | null;
  ipAddress: string | null;
}

export interface Settings {
  mode: ConnectionMode;
  backendUrl: string;
  apiKey: string;
}

export const DEFAULT_BACKEND_URL = 'http://192.168.1.100:8000';

export const DEFAULT_SETTINGS: Settings = {
  // iPhone-only build: default to direct phone-to-TV control so the app
  // works with no Python backend / laptop. Backend mode is still available
  // from Settings for brands direct mode cannot drive (Sony, Android TV,
  // Google TV, TCL, Fire TV).
  mode: 'direct',
  backendUrl: DEFAULT_BACKEND_URL,
  apiKey: '',
};

/** Exact message the backend (CONTRACTS.md §4) and this app use for Wi-Fi mismatch. */
export const SAME_WIFI_ERROR =
  'Your TV and smartphone must be connected to the same local Wi-Fi network.';

export interface ApiResult<T> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface ConnectionStatus {
  connected: boolean;
  device_id?: string;
  name?: string;
  brand?: string;
  ip?: string;
  last_error?: string;
}

export interface NetworkStatus {
  wifi_connected: boolean;
  ssid?: string | null;
  phone_ip?: string | null;
  backend_ip: string;
  subnet: string;
  validation: 'verified' | 'failed';
  message: string;
}

export interface HealthStatus {
  status: string;
}
