// TypeScript wrapper around the native SmartRemoteNative bridge (CONTRACTS.md §3).
// Native module name on both platforms: SmartRemoteNative.
// If the module is absent (plain JS environment / tests), every call rejects with
// a clear error — never fake network/discovery data.
import {NativeEventEmitter, NativeModules} from 'react-native';
import {DiscoveredTv, NetworkChangedEvent, NetworkInfo} from '../types';

type SmartRemoteNativeModule = {
  getNetworkInfo(): Promise<NetworkInfo>;
  startDiscovery(): Promise<void>;
  stopDiscovery(): Promise<void>;
  isWifiConnected(): Promise<boolean>;
};

const NATIVE_UNAVAILABLE_ERROR =
  'Native module SmartRemoteNative is not available. ' +
  'Discovery and network info require a real device build with the native module installed.';

function getNativeModule(): SmartRemoteNativeModule {
  const mod = (NativeModules as Record<string, unknown>).SmartRemoteNative as
    | SmartRemoteNativeModule
    | undefined;
  if (!mod) {
    throw new Error(NATIVE_UNAVAILABLE_ERROR);
  }
  return mod;
}

export function isNativeModuleAvailable(): boolean {
  return Boolean(
    (NativeModules as Record<string, unknown>).SmartRemoteNative,
  );
}

export async function getNetworkInfo(): Promise<NetworkInfo> {
  const info = await getNativeModule().getNetworkInfo();
  return {
    connected: Boolean(info.connected),
    isWifi: Boolean(info.isWifi),
    isCellular: Boolean(info.isCellular),
    ssid: info.ssid ?? null,
    bssid: info.bssid ?? null,
    ipAddress: info.ipAddress ?? null,
    subnetMask: info.subnetMask ?? null,
    gateway: info.gateway ?? null,
  };
}

export async function isWifiConnected(): Promise<boolean> {
  return getNativeModule().isWifiConnected();
}

export async function startDiscovery(): Promise<void> {
  await getNativeModule().startDiscovery();
}

export async function stopDiscovery(): Promise<void> {
  await getNativeModule().stopDiscovery();
}

export interface NativeSubscription {
  remove(): void;
}

function getEmitter(): NativeEventEmitter {
  // Throws if the native module is absent; the emitter is constructed from
  // the raw NativeModules entry, as React Native requires.
  getNativeModule();
  return new NativeEventEmitter(
    NativeModules.SmartRemoteNative as unknown as ConstructorParameters<
      typeof NativeEventEmitter
    >[0],
  );
  // Note: `mod` is only used for the availability check above; the emitter
  // is constructed from the raw NativeModules entry, as React Native requires.
}

/** Subscribe to 'TvDiscovered' events: {tv: DiscoveredTv}. */
export function addTvDiscoveredListener(
  listener: (tv: DiscoveredTv) => void,
): NativeSubscription {
  const emitter = getEmitter();
  const sub = emitter.addListener('TvDiscovered', (payload: unknown) => {
    const p = payload as {tv?: DiscoveredTv} | DiscoveredTv;
    const tv = (p as {tv?: DiscoveredTv}).tv ?? (p as DiscoveredTv);
    if (tv && typeof tv.ip === 'string') {
      listener(tv);
    }
  });
  return {remove: () => sub.remove()};
}

/** Subscribe to 'NetworkChanged' events: {connected, ssid, ipAddress}. */
export function addNetworkChangedListener(
  listener: (event: NetworkChangedEvent) => void,
): NativeSubscription {
  const emitter = getEmitter();
  const sub = emitter.addListener('NetworkChanged', (payload: unknown) => {
    const p = payload as NetworkChangedEvent;
    listener({
      connected: Boolean(p.connected),
      ssid: p.ssid ?? null,
      ipAddress: p.ipAddress ?? null,
    });
  });
  return {remove: () => sub.remove()};
}
