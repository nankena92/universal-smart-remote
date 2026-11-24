import React from 'react';
import {ScrollView, StyleSheet, Text, View} from 'react-native';
import {commonStyles} from '../theme';
import {useNetworkStatus} from '../hooks/useNetworkStatus';
import {useTvConnection} from '../hooks/useTvConnection';
import NetworkStatusCard from '../components/NetworkStatusCard';
import ControlButton from '../components/ControlButton';

interface Props {
  navigation: any;
}

export default function NetworkInfoScreen({navigation}: Props) {
  const {networkInfo, backendStatus, settings, loading, error, refresh} = useNetworkStatus();
  const {connectedTv} = useTvConnection();

  return (
    <ScrollView style={commonStyles.screen} contentContainerStyle={styles.content}>
      <Text style={commonStyles.title}>Network Info</Text>
      <Text style={[commonStyles.subtitle, styles.sub]}>
        Live network information from the native module
        {settings ? ` · Mode: ${settings.mode}` : ''}.
      </Text>
      {loading ? (
        <Text style={commonStyles.emptyText}>Loading network info…</Text>
      ) : (
        <NetworkStatusCard
          networkInfo={networkInfo}
          backendStatus={backendStatus}
          tvIp={connectedTv?.ip ?? null}
          tvConnected={Boolean(connectedTv)}
          error={error}
        />
      )}
      {networkInfo ? (
        <View style={[commonStyles.card, styles.detail]}>
          <Text style={styles.detailText}>SSID: {networkInfo.ssid ?? 'Unknown'}</Text>
          <Text style={styles.detailText}>BSSID: {networkInfo.bssid ?? 'Unknown'}</Text>
          <Text style={styles.detailText}>Subnet mask: {networkInfo.subnetMask ?? 'Unknown'}</Text>
          <Text style={styles.detailText}>Gateway: {networkInfo.gateway ?? 'Unknown'}</Text>
          <Text style={styles.detailText}>
            Connection: {networkInfo.isWifi ? 'Wi-Fi' : networkInfo.isCellular ? 'Cellular' : 'Not connected'}
          </Text>
          {backendStatus ? (
            <Text style={styles.detailText}>Backend subnet: {backendStatus.subnet}</Text>
          ) : null}
        </View>
      ) : null}
      <View style={styles.actions}>
        <ControlButton label="Refresh" variant="primary" onPress={() => void refresh()} />
        <ControlButton label="Back to Remote" onPress={() => navigation.navigate('Remote')} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {paddingBottom: 32, paddingTop: 16},
  sub: {marginTop: 8, marginBottom: 16},
  detail: {marginTop: 16, gap: 6},
  detailText: {color: '#A1A1B5', fontSize: 14},
  actions: {gap: 10, marginTop: 16},
});
