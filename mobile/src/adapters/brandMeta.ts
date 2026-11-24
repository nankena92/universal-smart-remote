// Per-brand metadata, mirroring CONTRACTS.md §1 (BRANDS) and apps.py (STREAMING_APPS).
// Used by the UI to disable unsupported buttons with an honest
// "not supported on this TV" label instead of pretending they work.
import {Brand, RemoteKey, StreamingAppId} from '../types';

export interface BrandMeta {
  brand: Brand;
  displayName: string;
  defaultPort: number;
  /** Features from TvAdapter.supports(): power, volume, mute, channel, media, launch_app, pairing */
  features: {
    power: boolean;
    volume: boolean;
    mute: boolean;
    channel: boolean;
    media: boolean;
    launchApp: boolean;
    pairing: boolean;
  };
  /** Direct (no-backend) control from the phone. */
  directSupported: boolean;
  directNote?: string;
}

export const BRAND_META: Record<string, BrandMeta> = {
  samsung: {
    brand: 'samsung',
    displayName: 'Samsung (Tizen)',
    defaultPort: 8001,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: true, pairing: true},
    directSupported: true,
  },
  lg: {
    brand: 'lg',
    displayName: 'LG (webOS)',
    defaultPort: 3000,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: true, pairing: true},
    directSupported: true,
  },
  sony: {
    brand: 'sony',
    displayName: 'Sony Bravia',
    defaultPort: 80,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: false, pairing: true},
    directSupported: false,
    directNote: 'Sony Bravia needs the backend (IRCC-IP) — direct mode is not supported.',
  },
  androidtv: {
    brand: 'androidtv',
    displayName: 'Android TV',
    defaultPort: 6466,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: false, pairing: true},
    directSupported: false,
    directNote: 'Android TV needs the backend (pairing + protobuf remote protocol) — direct mode is not supported.',
  },
  googletv: {
    brand: 'googletv',
    displayName: 'Google TV',
    defaultPort: 6466,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: false, pairing: true},
    directSupported: false,
    directNote: 'Google TV needs the backend — direct mode is not supported.',
  },
  tcl: {
    brand: 'tcl',
    displayName: 'TCL',
    defaultPort: 8060,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: true, pairing: false},
    directSupported: false,
    directNote: 'TCL delegates to Roku or Android TV depending on the model OS — use backend mode so the OS can be resolved.',
  },
  roku: {
    brand: 'roku',
    displayName: 'Roku TV',
    defaultPort: 8060,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: true, pairing: false},
    directSupported: true,
  },
  firetv: {
    brand: 'firetv',
    displayName: 'Amazon Fire TV',
    defaultPort: 5555,
    features: {power: true, volume: true, mute: true, channel: false, media: true, launchApp: true, pairing: false},
    directSupported: false,
    directNote: 'Fire TV needs ADB debugging enabled on the TV — use backend mode.',
  },
  mock: {
    brand: 'mock',
    displayName: 'Mock TV (testing only)',
    defaultPort: 0,
    features: {power: true, volume: true, mute: true, channel: true, media: true, launchApp: true, pairing: false},
    directSupported: false,
    directNote: 'Mock TV is only reachable when the backend is started with MOCK_TV=true.',
  },
  unknown: {
    brand: 'unknown',
    displayName: 'Unknown TV',
    defaultPort: 0,
    features: {power: false, volume: false, mute: false, channel: false, media: false, launchApp: false, pairing: false},
    directSupported: false,
    directNote: 'Brand could not be determined — connect via the backend so it can be identified.',
  },
};

export function normaliseBrand(raw: string | null | undefined): Brand {
  const b = (raw ?? '').trim().toLowerCase();
  if (b in BRAND_META) {
    return b as Brand;
  }
  if (b === 'google tv' || b === 'googletv') {
    return 'googletv';
  }
  if (b === 'android tv') {
    return 'androidtv';
  }
  if (b === 'fire tv') {
    return 'firetv';
  }
  return 'unknown';
}

export function getBrandMeta(brand: string | null | undefined): BrandMeta {
  return BRAND_META[normaliseBrand(brand)] ?? BRAND_META.unknown;
}

/** Streaming app ids, mirroring backend/app/adapters/apps.py exactly. null = not supported. */
export const STREAMING_APP_IDS: Record<
  StreamingAppId,
  Partial<Record<Brand, string | null>>
> = {
  netflix: {
    roku: '12',
    samsung: '3201907018807',
    lg: 'netflix',
    androidtv: 'com.netflix.ninja',
    firetv: 'com.netflix.ninja',
    sony: null,
    tcl: null,
  },
  prime: {
    roku: '13',
    samsung: '3201910019365',
    lg: 'amazon',
    androidtv: 'com.amazon.amazonvideo.livingroom',
    firetv: 'com.amazon.amazonvideo.livingroom',
    sony: null,
    tcl: null,
  },
  youtube: {
    roku: '837',
    samsung: '111299001912',
    lg: 'youtube',
    androidtv: 'com.google.android.youtube.tv',
    firetv: 'com.google.android.youtube.tv',
    sony: null,
    tcl: null,
  },
  disney: {
    roku: '291097',
    samsung: null,
    lg: null,
    androidtv: 'com.disney.disneyplus',
    firetv: 'com.disney.disneyplus',
    sony: null,
    tcl: null,
  },
};

export function getStreamingAppId(
  app: StreamingAppId,
  brand: string | null | undefined,
): string | null {
  const ids = STREAMING_APP_IDS[app];
  const value = ids[normaliseBrand(brand)];
  return value ?? null;
}

export function isAppSupportedOnBrand(
  app: StreamingAppId,
  brand: string | null | undefined,
): boolean {
  return getStreamingAppId(app, brand) !== null;
}

export const STREAMING_APPS: {
  id: StreamingAppId;
  label: string;
  backgroundColor: string;
}[] = [
  {id: 'netflix', label: 'Netflix', backgroundColor: '#E50914'},
  {id: 'prime', label: 'Prime Video', backgroundColor: '#00A8E1'},
  {id: 'youtube', label: 'YouTube', backgroundColor: '#FF0000'},
  {id: 'disney', label: 'Disney+', backgroundColor: '#113CCF'},
];

/** Human-readable reason a key/feature is unavailable on this TV. */
export function unsupportedLabel(feature: string, brand: string | null | undefined): string {
  return `${feature} not supported on ${getBrandMeta(brand).displayName}`;
}

export const ALL_REMOTE_KEYS: RemoteKey[] = [
  'up', 'down', 'left', 'right', 'ok', 'back', 'home', 'menu', 'power',
  'volume-up', 'volume-down', 'mute', 'channel-up', 'channel-down',
  'play', 'pause', 'stop', 'rewind', 'fast-forward',
];
