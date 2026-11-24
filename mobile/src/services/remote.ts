// Unified RemoteService: routes every command to the backend client or to
// the direct phone-to-TV clients depending on Settings.mode ('backend' | 'direct').
// Revalidates same-Wi-Fi (native getNetworkInfo + connected-TV IP subnet check)
// before EVERY command, throwing the exact CONTRACTS.md §4 error on failure.
// Never claims success on a failed command.
import {SAME_WIFI_ERROR, ConnectionStatus, DiscoveredTv, PairedTv, RemoteKey, StreamingAppId} from '../types';
import * as api from './api';
import {getNetworkInfo} from './native';
import {getBrandMeta, getStreamingAppId} from '../adapters/brandMeta';
import {rokuIsAppInstalled, rokuLaunchApp, rokuSendKey} from './direct/rokuDirect';
import {samsungDirect} from './direct/samsungDirect';
import {lgDirect} from './direct/lgDirect';
import {sameSubnet} from '../utils/network';
import {
  addPairedDevice,
  loadConnectedDeviceId,
  loadPairedDevices,
  loadSettings,
  saveConnectedDeviceId,
  clearConnectedDevice,
} from '../utils/storage';

export class RemoteService {
  private connectedTv: PairedTv | null = null;

  /** Restore the last connected TV from storage (call once at app start). */
  async restoreConnectedTv(): Promise<PairedTv | null> {
    const id = await loadConnectedDeviceId();
    if (!id) {
      return null;
    }
    const paired = await loadPairedDevices();
    const found = paired.find(d => d.id === id) ?? null;
    this.connectedTv = found;
    return found;
  }

  getConnectedTv(): PairedTv | null {
    return this.connectedTv;
  }

  async setConnectedTv(tv: PairedTv | null): Promise<void> {
    this.connectedTv = tv;
    if (tv) {
      await saveConnectedDeviceId(tv.id);
      await addPairedDevice({...tv, lastConnected: new Date().toISOString()});
    } else {
      await clearConnectedDevice();
    }
  }

  /** Revalidate same-Wi-Fi before a command. Throws SAME_WIFI_ERROR on failure. */
  async assertSameWifi(tvIp?: string): Promise<void> {
    const targetIp = tvIp ?? this.connectedTv?.ip;
    if (!targetIp) {
      throw new Error('No TV is connected. Connect to a TV first.');
    }
    let info;
    try {
      info = await getNetworkInfo();
    } catch (err) {
      throw new Error(
        `Cannot verify the TV and phone are on the same Wi-Fi network: ${
          err instanceof Error ? err.message : 'native network module unavailable'
        }`,
      );
    }
    if (!info.connected || !info.isWifi || !info.ipAddress) {
      throw new Error(SAME_WIFI_ERROR);
    }
    const mask = info.subnetMask ?? '255.255.255.0';
    if (!sameSubnet(info.ipAddress, targetIp, mask)) {
      throw new Error(SAME_WIFI_ERROR);
    }
  }

  async connectTv(tv: DiscoveredTv): Promise<void> {
    const settings = await loadSettings();
    if (settings.mode === 'backend') {
      // Send {ip, brand, name, ...} WITHOUT device_id: the backend's
      // POST /devices/connect looks a device_id up in its saved-devices DB
      // and 404s for a freshly discovered TV (whose id is only a local
      // `discovered-<ip>` / `manual-<ip>` label). With ip only, the backend
      // keys the device as `tv-<ip>` and preserves any stored pairing token
      // for that id on later connects.
      const result = await api.connectDevice({
        ip: tv.ip,
        brand: tv.brand,
        name: tv.name,
        model: tv.model || undefined,
        port: tv.port || undefined,
        mac: tv.mac || undefined,
      });
      if (!result.success) {
        throw new Error(result.error ?? 'Failed to connect to the TV via the backend.');
      }
    } else {
      // Direct mode: verify reachability for the brands that support it.
      await this.assertSameWifi(tv.ip);
      const brand = getBrandMeta(tv.brand);
      if (!brand.directSupported) {
        throw new Error(
          brand.directNote ??
            `Direct mode is not supported for ${brand.displayName}. Switch to backend mode in Settings.`,
        );
      }
      if (brand.brand === 'samsung') {
        await samsungDirect.connect(tv.ip);
      } else if (brand.brand === 'lg') {
        await lgDirect.connect(tv.ip);
      } else if (brand.brand === 'roku') {
        // Roku has no connect handshake; a query proves reachability.
        await rokuIsAppInstalled(tv.ip, '12').catch(() => {
          throw new Error(`Could not reach Roku TV at ${tv.ip}:8060. Check it is on and on the same Wi-Fi.`);
        });
      }
    }
    const paired: PairedTv = {...tv, paired: true};
    await this.setConnectedTv(paired);
  }

  /**
   * PIN pairing (backend mode only). `ip` lets the backend device id be
   * resolved from GET /devices: the id the backend knows is `tv-<ip>`,
   * not the local `discovered-<ip>` / `manual-<ip>` label, and
   * POST /devices/pair 404s for an id the backend has never saved.
   * Throws the backend's real error on failure — never a fake success.
   * NOTE: for a first-time Android TV the backend persists the pairing
   * session across the two requests (connect saves the device and keeps
   * the live adapter; pair reuses it), so pair can finish the handshake.
   * If the backend restarts between connect and pair, the session is
   * lost and pair honestly fails — connect again for a fresh code.
   */
  async pairTv(deviceId: string, pin?: string, ip?: string): Promise<ConnectionStatus> {
    const settings = await loadSettings();
    if (settings.mode !== 'backend') {
      throw new Error(
        'PIN pairing in direct mode happens on the TV itself when you first connect (Samsung Allow prompt / LG pairing prompt). No PIN is entered in the app.',
      );
    }
    let backendId = deviceId;
    if (ip) {
      try {
        const saved = await api.listDevices();
        const match = saved.data?.find(d => d.ip === ip);
        if (match) {
          backendId = match.id;
        } else if (deviceId.startsWith('discovered-') || deviceId.startsWith('manual-')) {
          // Backend keys ip-only connects as `tv-<ip>` (device_service).
          backendId = `tv-${ip}`;
        }
      } catch {
        // listDevices failure must not mask the pairing attempt; fall back
        // to the given id and let the backend report the real error.
      }
    }
    const result = await api.pairDevice(backendId, pin);
    if (!result.success || !result.data) {
      throw new Error(result.error ?? 'Pairing failed.');
    }
    if (!result.data.connected) {
      throw new Error(
        result.data.last_error ?? 'Pairing did not complete. The TV is not connected.',
      );
    }
    return result.data;
  }

  async disconnectTv(): Promise<void> {
    const tv = this.connectedTv;
    const settings = await loadSettings();
    if (settings.mode === 'backend' && tv) {
      const result = await api.disconnectDevice(tv.id);
      if (!result.success) {
        throw new Error(result.error ?? 'Failed to disconnect from the TV.');
      }
    }
    samsungDirect.disconnect();
    lgDirect.disconnect();
    await this.setConnectedTv(null);
  }

  async sendKey(key: RemoteKey): Promise<void> {
    const tv = this.connectedTv;
    if (!tv) {
      throw new Error('No TV is connected. Connect to a TV first.');
    }
    await this.assertSameWifi(tv.ip);
    const settings = await loadSettings();
    if (settings.mode === 'backend') {
      const result = await api.sendRemoteKey(key, tv.id);
      if (!result.success) {
        throw new Error(result.error ?? `Failed to send ${key} to the TV.`);
      }
      return;
    }
    // Direct mode
    const brand = getBrandMeta(tv.brand);
    if (!brand.directSupported) {
      throw new Error(
        brand.directNote ??
          `Direct mode is not supported for ${brand.displayName}. Switch to backend mode in Settings.`,
      );
    }
    if (brand.brand === 'roku') {
      await rokuSendKey(tv.ip, key);
    } else if (brand.brand === 'samsung') {
      await samsungDirect.sendKey(tv.ip, key);
    } else if (brand.brand === 'lg') {
      await lgDirect.sendKey(tv.ip, key);
    } else {
      throw new Error(`Direct mode is not supported for ${brand.displayName}.`);
    }
  }

  async launchApp(app: StreamingAppId): Promise<void> {
    const tv = this.connectedTv;
    if (!tv) {
      throw new Error('No TV is connected. Connect to a TV first.');
    }
    const settings = await loadSettings();
    await this.assertSameWifi(tv.ip);
    if (settings.mode === 'backend') {
      // Backend mode: the backend is the authority on launch support.
      // Its adapters decide per brand AND per host (e.g. Android TV launch
      // needs ADB on the backend host; TCL delegates to Roku/Android TV;
      // Sony launch_app is unsupported) and return an honest 422/503.
      // The phone's static app-id table must NOT pre-block those launches.
      const result = await api.launchApp(app, tv.id);
      if (!result.success) {
        throw new Error(result.error ?? `Failed to launch ${app}.`);
      }
      return;
    }
    // Direct mode — the phone's static table is the only authority, so
    // check support / app id here, then use the brand's direct client.
    const brand = getBrandMeta(tv.brand);
    if (!brand.features.launchApp) {
      throw new Error(
        `Launching apps is not supported on ${brand.displayName}.`,
      );
    }
    const appId = getStreamingAppId(app, tv.brand);
    if (appId === null) {
      throw new Error(
        `${app} is not supported/unknown for ${brand.displayName} — no documented app id exists for this brand.`,
      );
    }
    if (brand.brand === 'roku') {
      const installed = await rokuIsAppInstalled(tv.ip, appId);
      if (!installed) {
        throw new Error(`${app} is not installed on this Roku TV.`);
      }
      await rokuLaunchApp(tv.ip, appId);
    } else if (brand.brand === 'samsung') {
      await samsungDirect.launchApp(tv.ip, appId);
    } else if (brand.brand === 'lg') {
      await lgDirect.launchApp(tv.ip, appId);
    } else {
      throw new Error(
        `Direct app launch is not supported for ${brand.displayName}. Switch to backend mode in Settings.`,
      );
    }
  }
}

export const remoteService = new RemoteService();
