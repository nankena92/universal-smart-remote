// Roku direct client — Roku ECP over HTTP (CONTRACTS.md §5).
// http://<ip>:8060/keypress/<Key>, POST /launch/<appid>, GET /query/apps.
// No backend involved. Every call sends a real request and surfaces real errors.
import {RemoteKey} from '../../types';

const ROKU_PORT = 8060;
const REQUEST_TIMEOUT_MS = 8000;

const KEY_MAP: Record<RemoteKey, string> = {
  up: 'Up',
  down: 'Down',
  left: 'Left',
  right: 'Right',
  ok: 'Select',
  back: 'Back',
  home: 'Home',
  menu: 'Info',
  power: 'Power',
  'volume-up': 'VolumeUp',
  'volume-down': 'VolumeDown',
  mute: 'VolumeMute',
  'channel-up': 'ChannelUp',
  'channel-down': 'ChannelDown',
  play: 'Play',
  pause: 'Pause',
  stop: 'Stop',
  rewind: 'Rev',
  'fast-forward': 'Fwd',
};

function baseUrl(ip: string): string {
  return `http://${ip}:${ROKU_PORT}`;
}

async function fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, {...init, signal: controller.signal});
  } finally {
    clearTimeout(timer);
  }
}

function httpError(res: Response, action: string): Error {
  return new Error(`Roku ${action} failed: TV returned HTTP ${res.status}.`);
}

export async function rokuSendKey(ip: string, key: RemoteKey): Promise<void> {
  const ecpKey = KEY_MAP[key];
  if (!ecpKey) {
    throw new Error(`Roku does not support key: ${key}`);
  }
  let res: Response;
  try {
    res = await fetchWithTimeout(`${baseUrl(ip)}/keypress/${ecpKey}`, {method: 'POST'});
  } catch (err) {
    throw new Error(
      `Could not reach Roku TV at ${ip}: ${err instanceof Error ? err.message : 'network error'}`,
    );
  }
  if (!res.ok) {
    throw httpError(res, `keypress ${ecpKey}`);
  }
}

export async function rokuQueryApps(ip: string): Promise<{id: string; name: string}[]> {
  let res: Response;
  try {
    res = await fetchWithTimeout(`${baseUrl(ip)}/query/apps`, {method: 'GET'});
  } catch (err) {
    throw new Error(
      `Could not reach Roku TV at ${ip}: ${err instanceof Error ? err.message : 'network error'}`,
    );
  }
  if (!res.ok) {
    throw httpError(res, 'query apps');
  }
  const xml = await res.text();
  // /query/apps returns XML: <apps><app id="12">Netflix</app>...</apps>
  const apps: {id: string; name: string}[] = [];
  const re = /<app[^>]*id="([^"]+)"[^>]*>([^<]*)<\/app>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) {
    apps.push({id: m[1], name: (m[2] ?? '').trim()});
  }
  return apps;
}

export async function rokuIsAppInstalled(ip: string, appId: string): Promise<boolean> {
  const apps = await rokuQueryApps(ip);
  return apps.some(a => a.id === appId);
}

export async function rokuLaunchApp(ip: string, appId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetchWithTimeout(`${baseUrl(ip)}/launch/${appId}`, {method: 'POST'});
  } catch (err) {
    throw new Error(
      `Could not reach Roku TV at ${ip}: ${err instanceof Error ? err.message : 'network error'}`,
    );
  }
  if (!res.ok) {
    throw httpError(res, `launch app ${appId}`);
  }
}
