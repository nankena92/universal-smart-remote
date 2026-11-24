// Subnet / IP helpers for same-Wi-Fi validation (CONTRACTS.md §4).

export function parseIPv4(ip: string | null | undefined): number[] | null {
  if (!ip) {
    return null;
  }
  const parts = ip.trim().split('.');
  if (parts.length !== 4) {
    return null;
  }
  const nums = parts.map(p => {
    if (!/^\d+$/.test(p)) {
      return NaN;
    }
    return Number(p);
  });
  if (nums.some(n => Number.isNaN(n) || n < 0 || n > 255)) {
    return null;
  }
  return nums as number[];
}

export function isValidIp(ip: string | null | undefined): boolean {
  return parseIPv4(ip) !== null;
}

export function ipToInt(ip: string): number | null {
  const parts = parseIPv4(ip);
  if (!parts) {
    return null;
  }
  // Use unsigned arithmetic; >>> 0 keeps the value in uint32 range.
  return (
    (((parts[0] << 24) >>> 0) +
      ((parts[1] << 16) >>> 0) +
      ((parts[2] << 8) >>> 0) +
      (parts[3] >>> 0)) >>>
    0
  );
}

/** Convert a dotted mask (255.255.255.0) or a CIDR prefix length to a uint32 mask. */
export function maskToInt(mask: string | number | null | undefined): number {
  if (typeof mask === 'number') {
    if (mask <= 0) {
      return 0;
    }
    if (mask >= 32) {
      return 0xffffffff;
    }
    return (0xffffffff << (32 - mask)) >>> 0;
  }
  const parsed = parseIPv4(mask ?? undefined);
  if (parsed) {
    const v = ipToInt(mask as string);
    return v === null ? 0xffffff00 : v;
  }
  return 0xffffff00; // default /24
}

export function sameSubnet(
  ipA: string | null | undefined,
  ipB: string | null | undefined,
  mask: string | number = '255.255.255.0',
): boolean {
  const a = ipToInt(ipA ?? '');
  const b = ipToInt(ipB ?? '');
  if (a === null || b === null) {
    return false;
  }
  const m = maskToInt(mask);
  return (a & m) === (b & m);
}

export function isPrivateIp(ip: string | null | undefined): boolean {
  const parts = parseIPv4(ip);
  if (!parts) {
    return false;
  }
  const [a, b] = parts;
  if (a === 10) {
    return true;
  }
  if (a === 172 && b >= 16 && b <= 31) {
    return true;
  }
  if (a === 192 && b === 168) {
    return true;
  }
  if (a === 169 && b === 254) {
    return true; // link-local
  }
  return false;
}

/** "192.168.1.42" + "255.255.255.0" -> "192.168.1.0/24" (best effort). */
export function subnetOf(ip: string, mask: string | number = '255.255.255.0'): string {
  const intIp = ipToInt(ip);
  if (intIp === null) {
    return '';
  }
  const m = maskToInt(mask);
  const net = (intIp & m) >>> 0;
  const octets = [
    (net >>> 24) & 0xff,
    (net >>> 16) & 0xff,
    (net >>> 8) & 0xff,
    net & 0xff,
  ];
  const prefix =
    typeof mask === 'number'
      ? mask
      : m
          .toString(2)
          .split('')
          .filter(c => c === '1').length;
  return `${octets.join('.')}/${prefix}`;
}
