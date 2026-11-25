// Samsung Tizen direct client — WebSocket (CONTRACTS.md §5).
// wss://<ip>:8002/api/v2/channels/samsung.remote.control?name=<base64(name)>
// First connect without a token shows an Allow prompt on the TV; accepting it
// returns ms.channel.connect with a token, persisted and reused afterwards.
// Keys: ms.remote.control {Cmd: "Click", DataOfCmd: KEY_*, TypeOfRemote: "SendRemoteKey"}
// Launch: ms.channel.emit {event: "ed.apps.launch", ...} with the Tizen app id.
// The TV uses a self-signed certificate; the Python backend bypasses that
// with an unverified SSL context, but React Native's WebSocket does not
// expose a certificate-bypass option. So this client tries the secure
// channel first and, if it cannot be established at all (e.g. the platform
// rejects the self-signed certificate), falls back to plain
// ws://<ip>:8001 — mirroring the backend adapter's fallback. An explicit
// ms.channel.unauthorized (Allow denied) is NOT retried on plain ws.
// NEEDS ON-DEVICE VERIFICATION (see CONTRACTS.md §7): whether this TV
// accepts the plain channel, and whether wss works at all from the app,
// can only be settled on the real phone + TV.
import {RemoteKey} from '../../types';
import {loadSamsungToken, saveSamsungToken} from '../../utils/storage';

const SAMSUNG_SECURE_PORT = 8002;
const SAMSUNG_PLAIN_PORT = 8001;
const CONNECT_TIMEOUT_MS = 30000; // per attempt; TV Allow prompt can take a while
const SEND_TIMEOUT_MS = 10000;

const KEY_MAP: Record<RemoteKey, string> = {
  up: 'KEY_UP',
  down: 'KEY_DOWN',
  left: 'KEY_LEFT',
  right: 'KEY_RIGHT',
  ok: 'KEY_ENTER',
  back: 'KEY_RETURN',
  home: 'KEY_HOME',
  menu: 'KEY_MENU',
  power: 'KEY_POWER',
  'volume-up': 'KEY_VOLUP',
  'volume-down': 'KEY_VOLDOWN',
  mute: 'KEY_MUTE',
  'channel-up': 'KEY_CHUP',
  'channel-down': 'KEY_CHDOWN',
  play: 'KEY_PLAY',
  pause: 'KEY_PAUSE',
  stop: 'KEY_STOP',
  rewind: 'KEY_REWIND',
  'fast-forward': 'KEY_FF',
};

/** Minimal base64 encoder (React Native has no btoa/Buffer by default). */
export function base64Encode(input: string): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let out = '';
  for (let i = 0; i < input.length; i += 3) {
    const a = input.charCodeAt(i) & 0xff;
    const b = i + 1 < input.length ? input.charCodeAt(i + 1) & 0xff : 0;
    const c = i + 2 < input.length ? input.charCodeAt(i + 2) & 0xff : 0;
    const n = (a << 16) | (b << 8) | c;
    out += chars[(n >> 18) & 63] + chars[(n >> 12) & 63];
    out += i + 1 < input.length ? chars[(n >> 6) & 63] : '=';
    out += i + 2 < input.length ? chars[n & 63] : '=';
  }
  return out;
}

interface SamsungMessage {
  event?: string;
  data?: {token?: string};
  [key: string]: unknown;
}

export class SamsungDirectClient {
  private ws: WebSocket | null = null;
  private ip: string | null = null;
  private connectPromise: Promise<void> | null = null;

  get connected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  async connect(ip: string, deviceName = 'Universal Smart Remote'): Promise<void> {
    if (this.connected && this.ip === ip) {
      return;
    }
    if (this.connectPromise && this.ip === ip) {
      return this.connectPromise;
    }
    this.ip = ip;
    this.connectPromise = this.doConnect(ip, deviceName);
    try {
      await this.connectPromise;
    } finally {
      this.connectPromise = null;
    }
  }

  private async doConnect(ip: string, deviceName: string): Promise<void> {
    const token = await loadSamsungToken(ip);
    const name = base64Encode(deviceName);
    let lastError: Error | null = null;
    // Secure first, plain ws://:8001 second (see header note).
    for (const secure of [true, false]) {
      const port = secure ? SAMSUNG_SECURE_PORT : SAMSUNG_PLAIN_PORT;
      let url =
        `${secure ? 'wss' : 'ws'}://${ip}:${port}/api/v2/channels/samsung.remote.control` +
        `?name=${encodeURIComponent(name)}`;
      if (token) {
        url += `&token=${encodeURIComponent(token)}`;
      }
      try {
        await this.tryConnectOnce(ip, url, port);
        return;
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err));
        // An explicit refusal means the TV said no — retrying on the
        // plain channel cannot help, so stop here with the real reason.
        if (lastError.message.includes('refused the connection')) {
          throw lastError;
        }
        // Otherwise (cert rejected, connection refused, timeout, closed):
        // fall through to the next attempt, or throw after the last one.
      }
    }
    throw (
      lastError ??
      new Error(
        `Could not connect to Samsung TV at ${ip}. Check the TV is on, on the same Wi-Fi, and IP Remote is enabled.`,
      )
    );
  }

  private tryConnectOnce(ip: string, url: string, port: number): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      let settled = false;
      let ws: WebSocket | null = null;
      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          try {
            ws?.close();
          } catch {
            // ignore
          }
          reject(
            new Error(
              'Timed out waiting for the Samsung TV to accept the connection. ' +
                'Check the TV shows an Allow prompt and accept it.',
            ),
          );
        }
      }, CONNECT_TIMEOUT_MS);
      ws = new WebSocket(url);
      this.ws = ws;
      ws.onopen = () => {
        // Wait for ms.channel.connect (carries the token) before resolving.
      };
      ws.onmessage = (event: {data?: unknown}) => {
        let msg: SamsungMessage;
        try {
          msg = JSON.parse(String(event.data)) as SamsungMessage;
        } catch {
          return;
        }
        if (msg.event === 'ms.channel.connect') {
          if (msg.data?.token) {
            void saveSamsungToken(ip, msg.data.token);
          }
          if (!settled) {
            settled = true;
            clearTimeout(timer);
            resolve();
          }
        } else if (msg.event === 'ms.channel.unauthorized') {
          if (!settled) {
            settled = true;
            clearTimeout(timer);
            reject(
              new Error(
                'Samsung TV refused the connection. The Allow prompt was denied, ' +
                  'or this phone is blocked in the TV Device Connection Manager.',
              ),
            );
          }
        }
      };
      ws.onerror = () => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(
            new Error(
              `Could not connect to Samsung TV at ${ip}:${port}. ` +
                'Check the TV is on, on the same Wi-Fi, and IP Remote is enabled.',
            ),
          );
        }
      };
      ws.onclose = () => {
        this.ws = null;
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error(`Samsung TV at ${ip} closed the connection.`));
        }
      };
    });
  }

  private requireSocket(): WebSocket {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.ip) {
      throw new Error('Not connected to a Samsung TV. Connect first.');
    }
    return this.ws;
  }

  async sendKey(ip: string, key: RemoteKey): Promise<void> {
    await this.connect(ip);
    const samsungKey = KEY_MAP[key];
    if (!samsungKey) {
      throw new Error(`Samsung does not support key: ${key}`);
    }
    const ws = this.requireSocket();
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Timed out sending key to Samsung TV.')), SEND_TIMEOUT_MS);
      try {
        ws.send(
          JSON.stringify({
            method: 'ms.remote.control',
            params: {
              Cmd: 'Click',
              DataOfCmd: samsungKey,
              Option: 'false',
              TypeOfRemote: 'SendRemoteKey',
            },
          }),
        );
        clearTimeout(timer);
        resolve();
      } catch (err) {
        clearTimeout(timer);
        reject(err instanceof Error ? err : new Error('Failed to send key to Samsung TV.'));
      }
    });
  }

  async launchApp(ip: string, appId: string): Promise<void> {
    await this.connect(ip);
    const ws = this.requireSocket();
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Timed out launching app on Samsung TV.')), SEND_TIMEOUT_MS);
      try {
        ws.send(
          JSON.stringify({
            method: 'ms.channel.emit',
            params: {
              event: 'ed.apps.launch',
              to: 'host',
              data: {appId, action_type: 'NATIVE_LAUNCH'},
            },
          }),
        );
        clearTimeout(timer);
        resolve();
      } catch (err) {
        clearTimeout(timer);
        reject(err instanceof Error ? err : new Error('Failed to launch app on Samsung TV.'));
      }
    });
  }

  disconnect(): void {
    try {
      this.ws?.close();
    } catch {
      // ignore
    }
    this.ws = null;
    this.ip = null;
  }
}

export const samsungDirect = new SamsungDirectClient();
