// AsyncStorage helpers for settings + paired devices.
// All reads return safe defaults on missing/corrupt data — never throw to callers
// for a storage problem; callers surface an honest error instead where it matters.
import AsyncStorage from '@react-native-async-storage/async-storage';
import {DEFAULT_SETTINGS, PairedTv, Settings} from '../types';

const KEYS = {
  settings: '@smart_remote/settings',
  pairedDevices: '@smart_remote/paired_devices',
  connectedDeviceId: '@smart_remote/connected_device_id',
  samsungToken: '@smart_remote/samsung_token',
  lgClientKey: '@smart_remote/lg_client_key',
};

export async function loadSettings(): Promise<Settings> {
  try {
    const raw = await AsyncStorage.getItem(KEYS.settings);
    if (!raw) {
      return {...DEFAULT_SETTINGS};
    }
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      mode: parsed.mode === 'direct' ? 'direct' : 'backend',
      backendUrl:
        typeof parsed.backendUrl === 'string' && parsed.backendUrl.trim()
          ? parsed.backendUrl.trim()
          : DEFAULT_SETTINGS.backendUrl,
      apiKey: typeof parsed.apiKey === 'string' ? parsed.apiKey : '',
    };
  } catch {
    return {...DEFAULT_SETTINGS};
  }
}

export async function saveSettings(settings: Settings): Promise<void> {
  await AsyncStorage.setItem(KEYS.settings, JSON.stringify(settings));
}

export async function loadPairedDevices(): Promise<PairedTv[]> {
  try {
    const raw = await AsyncStorage.getItem(KEYS.pairedDevices);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as PairedTv[]) : [];
  } catch {
    return [];
  }
}

export async function savePairedDevices(devices: PairedTv[]): Promise<void> {
  await AsyncStorage.setItem(KEYS.pairedDevices, JSON.stringify(devices));
}

export async function addPairedDevice(device: PairedTv): Promise<PairedTv[]> {
  const existing = await loadPairedDevices();
  const next = [
    ...existing.filter(d => d.id !== device.id && d.ip !== device.ip),
    {...device, paired: true},
  ];
  await savePairedDevices(next);
  return next;
}

export async function removePairedDevice(deviceId: string): Promise<PairedTv[]> {
  const existing = await loadPairedDevices();
  const next = existing.filter(d => d.id !== deviceId);
  await savePairedDevices(next);
  const connectedId = await loadConnectedDeviceId();
  if (connectedId === deviceId) {
    await clearConnectedDevice();
  }
  return next;
}

export async function forgetAllPairedDevices(): Promise<void> {
  await AsyncStorage.removeItem(KEYS.pairedDevices);
  await clearConnectedDevice();
}

export async function loadConnectedDeviceId(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(KEYS.connectedDeviceId);
  } catch {
    return null;
  }
}

export async function saveConnectedDeviceId(deviceId: string): Promise<void> {
  await AsyncStorage.setItem(KEYS.connectedDeviceId, deviceId);
}

export async function clearConnectedDevice(): Promise<void> {
  await AsyncStorage.removeItem(KEYS.connectedDeviceId);
}

// --- Per-brand pairing tokens (direct mode) ---

export async function loadSamsungToken(ip: string): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(`${KEYS.samsungToken}:${ip}`);
  } catch {
    return null;
  }
}

export async function saveSamsungToken(ip: string, token: string): Promise<void> {
  await AsyncStorage.setItem(`${KEYS.samsungToken}:${ip}`, token);
}

export async function loadLgClientKey(ip: string): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(`${KEYS.lgClientKey}:${ip}`);
  } catch {
    return null;
  }
}

export async function saveLgClientKey(ip: string, clientKey: string): Promise<void> {
  await AsyncStorage.setItem(`${KEYS.lgClientKey}:${ip}`, clientKey);
}
