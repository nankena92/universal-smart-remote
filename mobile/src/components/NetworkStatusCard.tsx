import React from 'react';
import {StyleSheet, Text, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {NetworkInfo, NetworkStatus, SAME_WIFI_ERROR} from '../types';
import {sameSubnet} from '../utils/network';

interface NetworkStatusCardProps {
  networkInfo: NetworkInfo | null;
  backendStatus?: NetworkStatus | null;
  tvIp?: string | null;
  tvConnected: boolean;
  error?: string | null;
}

/** Phone Wi-Fi / Phone IP / TV IP / Network Validation / TV Connection. */
export default function NetworkStatusCard({
  networkInfo,
  backendStatus,
  tvIp,
  tvConnected,
  error,
}: NetworkStatusCardProps) {
  // Backend validation (GET /network/status) when in backend mode; in
  // direct mode there is no backend, so validate locally: the phone must
  // be on Wi-Fi and the TV's IP in the phone's subnet. Either way a failed
  // validation shows the exact CONTRACTS.md §4 message, not the backend's
  // paraphrase of it.
  const localValidation: 'verified' | 'failed' | undefined =
    networkInfo && tvIp
      ? networkInfo.isWifi && networkInfo.ipAddress && sameSubnet(networkInfo.ipAddress, tvIp, networkInfo.subnetMask ?? '255.255.255.0')
        ? 'verified'
        : 'failed'
      : undefined;
  const validation = backendStatus?.validation ?? localValidation;
  const validationLabel =
    validation === 'verified' ? 'Verified' : validation === 'failed' ? 'Failed' : 'Unknown';
  const rows: {label: string; value: string; ok?: boolean}[] = [
    {
      label: 'Phone Wi-Fi',
      value: networkInfo
        ? networkInfo.isWifi
          ? networkInfo.ssid ?? 'Connected (SSID unknown)'
          : networkInfo.isCellular
            ? 'Cellular — not Wi-Fi'
            : 'Not connected'
        : 'Unknown',
      ok: networkInfo?.isWifi,
    },
    {label: 'Phone IP', value: networkInfo?.ipAddress ?? 'Unknown'},
    {label: 'TV IP', value: tvIp ?? 'No TV connected'},
    {
      label: 'Network Validation',
      value: validationLabel,
      ok: validation === 'verified' ? true : validation === 'failed' ? false : undefined,
    },
    {
      label: 'TV Connection',
      value: tvConnected ? 'Connected' : 'Disconnected',
      ok: tvConnected,
    },
  ];
  if (backendStatus?.message) {
    rows.push({label: 'Backend', value: backendStatus.message});
  }
  return (
    <View style={commonStyles.card}>
      {rows.map(row => (
        <View key={row.label} style={styles.row}>
          <Text style={styles.label}>{row.label}</Text>
          <Text
            style={[
              styles.value,
              row.ok === true && styles.ok,
              row.ok === false && styles.bad,
            ]}>
            {row.value}
          </Text>
        </View>
      ))}
      {validation === 'failed' ? (
        <Text style={[commonStyles.errorText, styles.error]}>{SAME_WIFI_ERROR}</Text>
      ) : null}
      {error && error !== SAME_WIFI_ERROR ? (
        <Text style={[commonStyles.errorText, styles.error]}>{error}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 12,
  },
  label: {color: colors.textSecondary, fontSize: 14},
  value: {color: colors.text, fontSize: 14, fontWeight: '600', textAlign: 'right', flexShrink: 1},
  ok: {color: colors.success},
  bad: {color: colors.error},
  error: {marginTop: 12},
});
