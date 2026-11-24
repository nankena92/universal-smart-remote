// LG webOS direct client — SSAP over WebSocket (CONTRACTS.md §5).
// Transport: wss://<ip>:3001 (self-signed cert; required on firmware since ~2023),
// fallback ws://<ip>:3000 for older sets. Register handshake with forcePairing /
// PROMPT; the TV returns a client-key in the `registered` payload, persisted
// and reused afterwards.
// Buttons are NOT ssap:// calls: they go over a second socket obtained via
// ssap://com.webos.service.networkinput/getPointerInputSocket, as plain text
//   type:button\nname:UP\n\n
// (verified against the documented webOS / lgtv2 protocol; see file notes).
// Verified ssap:// calls used here:
//   ssap://audio/volumeUp, ssap://audio/volumeDown, ssap://audio/setMute,
//   ssap://audio/setVolume, ssap://system/turnOff,
//   ssap://system.launcher/launch {"id": appId},
//   ssap://tv/channelUp, ssap://tv/channelDown,
//   ssap://media.controls/play|pause|stop|rewind|fastForward
// NOTE: CONTRACTS.md §5 lists volume as ssap://audio/volume/up|down; the
// documented webOS API uses volumeUp/volumeDown, which is what is implemented.
// NEEDS ON-DEVICE VERIFICATION (see CONTRACTS.md §7) — in particular the
// register manifest below carries no signed block, and React Native's
// WebSocket cannot bypass the TV's self-signed certificate check.
import {RemoteKey} from '../../types';
import {loadLgClientKey, saveLgClientKey} from '../../utils/storage';

const LG_SECURE_PORT = 3001;
const LG_PLAIN_PORT = 3000;
const REGISTER_TIMEOUT_MS = 60000; // on-screen pairing prompt
const REQUEST_TIMEOUT_MS = 10000;

const BUTTON_MAP: Record<string, string> = {
  up: 'UP',
  down: 'DOWN',
  left: 'LEFT',
  right: 'RIGHT',
  ok: 'ENTER',
  back: 'BACK',
  home: 'HOME',
  menu: 'MENU',
};

const SSAP_KEY_MAP: Partial<Record<RemoteKey, {uri: string; payload?: Record<string, unknown>}>> = {
  'volume-up': {uri: 'ssap://audio/volumeUp'},
  'volume-down': {uri: 'ssap://audio/volumeDown'},
  mute: {uri: 'ssap://audio/setMute', payload: {mute: true}},
  power: {uri: 'ssap://system/turnOff'},
  'channel-up': {uri: 'ssap://tv/channelUp'},
  'channel-down': {uri: 'ssap://tv/channelDown'},
  play: {uri: 'ssap://media.controls/play'},
  pause: {uri: 'ssap://media.controls/pause'},
  stop: {uri: 'ssap://media.controls/stop'},
  rewind: {uri: 'ssap://media.controls/rewind'},
  'fast-forward': {uri: 'ssap://media.controls/fastForward'},
};

const REGISTER_MANIFEST = {
  manifest: {
    manifestVersion: 1,
    appVersion: '1.0.0',
    signed: {
      created: '20240101',
      appId: 'com.universal.smartremote',
      vendorId: 'com.universal.smartremote',
      localizedAppNames: {'': 'Universal Smart Remote'},
      localizedVendorNames: {'': 'Universal Smart Remote'},
      permissions: [
        'LAUNCH',
        'LAUNCH_WEBAPP',
        'APP_TO_APP',
        'CLOSE',
        'CONTROL_AUDIO',
        'CONTROL_INPUT_MEDIA_PLAYBACK',
        'CONTROL_INPUT_TV',
        'CONTROL_MOUSE_AND_KEYBOARD',
        'CONTROL_POWER',
        'READ_CURRENT_CHANNEL',
        'READ_INSTALLED_APPS',
        'READ_RUNNING_APPS',
        'READ_TV_CHANNEL_LIST',
        'WRITE_NOTIFICATION_TOAST',
      ],
      serial: '00000000000000000000000000000000',
    },
    permissions: [
      'LAUNCH',
      'LAUNCH_WEBAPP',
      'APP_TO_APP',
      'CLOSE',
      'CONTROL_AUDIO',
      'CONTROL_INPUT_MEDIA_PLAYBACK',
      'CONTROL_INPUT_TV',
      'CONTROL_MOUSE_AND_KEYBOARD',
      'CONTROL_POWER',
      'READ_CURRENT_CHANNEL',
      'READ_INSTALLED_APPS',
      'READ_RUNNING_APPS',
      'READ_TV_CHANNEL_LIST',
      'WRITE_NOTIFICATION_TOAST',
    ],
    signatures: [],
  },
};

interface SsapMessage {
  type?: string;
  id?: string;
  payload?: {'client-key'?: string; socketPath?: string; [key: string]: unknown};
  error?: string;
  [key: string]: unknown;
}

export class LgDirectClient {
  private ws: WebSocket | null = null;
  private inputWs: WebSocket | null = null;
  private ip: string | null = null;
  private nextId = 1;
  private pending = new Map<
    string,
    {resolve: (msg: SsapMessage) => void; reject: (err: Error) => void; timer: ReturnType<typeof setTimeout>}
  >();
  private connectPromise: Promise<void> | null = null;

  get connected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  async connect(ip: string): Promise<void> {
    if (this.connected && this.ip === ip) {
      return;
    }
    if (this.connectPromise && this.ip === ip) {
      return this.connectPromise;
    }
    this.ip = ip;
    this.connectPromise = this.doConnect(ip);
    try {
      await this.connectPromise;
    } finally {
      this.connectPromise = null;
    }
  }

  private doConnect(ip: string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const tryUrl = (url: string, isFallback: boolean): void => {
        let settled = false;
        const timer = setTimeout(() => {
          if (!settled) {
            settled = true;
            try {
              ws.close();
            } catch {
              // ignore
            }
            reject(
              new Error(
                'Timed out waiting for the LG TV pairing prompt. Accept the prompt on the TV, or check the TV is on and on the same Wi-Fi.',
              ),
            );
          }
        }, REGISTER_TIMEOUT_MS);
        const ws = new WebSocket(url);
        this.ws = ws;
        ws.onopen = () => {
          const run = async () => {
            const clientKey = await loadLgClientKey(ip);
            const payload: Record<string, unknown> = {
              forcePairing: false,
              pairingType: 'PROMPT',
              ...REGISTER_MANIFEST,
            };
            if (clientKey) {
              payload['client-key'] = clientKey;
            }
            ws.send(JSON.stringify({type: 'register', id: 'register_0', payload}));
          };
          void run().catch(err => {
            if (!settled) {
              settled = true;
              clearTimeout(timer);
              reject(err instanceof Error ? err : new Error('LG registration failed.'));
            }
          });
        };
        ws.onmessage = (event: {data?: unknown}) => {
          let msg: SsapMessage;
          try {
            msg = JSON.parse(String(event.data)) as SsapMessage;
          } catch {
            return;
          }
          if (msg.type === 'registered') {
            if (msg.payload?.['client-key']) {
              void saveLgClientKey(ip, String(msg.payload['client-key']));
            }
            if (!settled) {
              settled = true;
              clearTimeout(timer);
              resolve();
            }
            return;
          }
          if (msg.type === 'error' && msg.id === 'register_0') {
            if (!settled) {
              settled = true;
              clearTimeout(timer);
              reject(
                new Error(
                  `LG TV refused registration: ${msg.error ?? 'unknown error'}. ` +
                    'Accept the pairing prompt on the TV and try again.',
                ),
              );
            }
            return;
          }
          const pending = msg.id ? this.pending.get(msg.id) : undefined;
          if (pending) {
            this.pending.delete(msg.id as string);
            clearTimeout(pending.timer);
            if (msg.type === 'error') {
              pending.reject(new Error(`LG TV returned an error: ${msg.error ?? 'unknown error'}`));
            } else {
              pending.resolve(msg);
            }
          }
        };
        ws.onerror = () => {
          if (isFallback) {
            if (!settled) {
              settled = true;
              clearTimeout(timer);
              reject(
                new Error(
                  `Could not connect to LG TV at ${ip} (ports 3001/3000). ` +
                    'Check the TV is on, on the same Wi-Fi, and LG Connect Apps / Mobile TV On is enabled. ' +
                    'Note: the TV uses a self-signed certificate — see NEEDS ON-DEVICE VERIFICATION in lgDirect.ts.',
                ),
              );
            }
          } else {
            // Fall back to plain ws://:3000 for older sets.
            clearTimeout(timer);
            try {
              ws.close();
            } catch {
              // ignore
            }
            tryUrl(`ws://${ip}:${LG_PLAIN_PORT}`, true);
          }
        };
        ws.onclose = () => {
          this.ws = null;
          this.inputWs = null;
          if (!settled) {
            settled = true;
            clearTimeout(timer);
            reject(new Error(`LG TV at ${ip} closed the connection.`));
          }
        };
      };
      tryUrl(`wss://${ip}:${LG_SECURE_PORT}`, false);
    });
  }

  private requireSocket(): WebSocket {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('Not connected to an LG TV. Connect first.');
    }
    return this.ws;
  }

  private request(uri: string, payload: Record<string, unknown> = {}): Promise<SsapMessage> {
    const ws = this.requireSocket();
    const id = `req_${this.nextId++}`;
    return new Promise<SsapMessage>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`LG TV did not respond to ${uri}.`));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, {resolve, reject, timer});
      try {
        ws.send(JSON.stringify({type: 'request', id, uri, payload}));
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err instanceof Error ? err : new Error(`Failed to send ${uri} to LG TV.`));
      }
    });
  }

  private async getInputSocket(): Promise<WebSocket> {
    if (this.inputWs && this.inputWs.readyState === WebSocket.OPEN) {
      return this.inputWs;
    }
    const res = await this.request('ssap://com.webos.service.networkinput/getPointerInputSocket', {});
    const socketPath = res.payload?.socketPath;
    if (typeof socketPath !== 'string' || !socketPath) {
      throw new Error('LG TV did not return a pointer-input socket path.');
    }
    const inputWs = await new Promise<WebSocket>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Timed out opening the LG input socket.')), REQUEST_TIMEOUT_MS);
      const sock = new WebSocket(socketPath);
      sock.onopen = () => {
        clearTimeout(timer);
        resolve(sock);
      };
      sock.onerror = () => {
        clearTimeout(timer);
        reject(new Error('Could not open the LG input socket.'));
      };
    });
    this.inputWs = inputWs;
    return inputWs;
  }

  private async sendButton(buttonName: string): Promise<void> {
    const sock = await this.getInputSocket();
    await new Promise<void>((resolve, reject) => {
      try {
        sock.send(`type:button\nname:${buttonName}\n\n`);
        resolve();
      } catch (err) {
        reject(err instanceof Error ? err : new Error('Failed to send button to LG TV.'));
      }
    });
  }

  async sendKey(ip: string, key: RemoteKey): Promise<void> {
    await this.connect(ip);
    const button = BUTTON_MAP[key];
    if (button) {
      await this.sendButton(button);
      return;
    }
    const ssap = SSAP_KEY_MAP[key];
    if (ssap) {
      await this.request(ssap.uri, ssap.payload ?? {});
      return;
    }
    throw new Error(`LG direct mode does not support key: ${key}`);
  }

  async launchApp(ip: string, appId: string): Promise<void> {
    await this.connect(ip);
    await this.request('ssap://system.launcher/launch', {id: appId});
  }

  disconnect(): void {
    try {
      this.inputWs?.close();
    } catch {
      // ignore
    }
    try {
      this.ws?.close();
    } catch {
      // ignore
    }
    this.ws = null;
    this.inputWs = null;
    this.ip = null;
  }
}

export const lgDirect = new LgDirectClient();
