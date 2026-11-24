import React, {useCallback, useEffect, useState} from 'react';
import {ScrollView, StyleSheet, Text, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {PairedTv} from '../types';
import {useTvConnection} from '../hooks/useTvConnection';
import {useNetworkStatus} from '../hooks/useNetworkStatus';
import {loadPairedDevices, loadSettings, removePairedDevice} from '../utils/storage';
import {listDevices} from '../services/api';
import {remoteService} from '../services/remote';
import ConnectionBadge from '../components/ConnectionBadge';
import ControlButton from '../components/ControlButton';
import DeviceListItem from '../components/DeviceListItem';
import NetworkStatusCard from '../components/NetworkStatusCard';
import {getBrandMeta} from '../adapters/brandMeta';

interface Props {
  navigation: any;
}

export default function HomeScreen({navigation}: Props) {
  const {connectedTv, loading, error, sendKey, disconnect, refresh: refreshConnection} = useTvConnection();
  const {networkInfo, backendStatus, error: netError} = useNetworkStatus();
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [disconnecting, setDisconnecting] = React.useState(false);
  const [savedTvs, setSavedTvs] = useState<PairedTv[]>([]);
  const [savedLoading, setSavedLoading] = useState(true);
  const [reconnectingId, setReconnectingId] = useState<string | null>(null);

  const refreshSaved = useCallback(async () => {
    setSavedLoading(true);
    try {
      // Same merge as Connect TV: on-phone storage + backend GET /devices,
      // deduped by IP.
      const local = await loadPairedDevices();
      let merged = [...local];
      try {
        const settings = await loadSettings();
        if (settings.mode === 'backend') {
          const result = await listDevices();
          if (result.success && result.data) {
            for (const saved of result.data) {
              if (!merged.some(d => d.ip === saved.ip)) {
                merged = [...merged, saved];
              }
            }
          }
        }
      } catch {
        // Backend unreachable: local saved TVs are still listed.
      }
      setSavedTvs(merged);
    } finally {
      setSavedLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSaved();
  }, [refreshSaved, connectedTv?.id]);

  const quick = async (key: 'power' | 'mute' | 'volume-up' | 'volume-down') => {
    const ok = await sendKey(key);
    setActionError(ok ? null : error);
  };

  const onDisconnect = async () => {
    setDisconnecting(true);
    const ok = await disconnect();
    setDisconnecting(false);
    if (!ok) {
      setActionError(error);
    } else {
      void refreshSaved();
    }
  };

  const reconnectSaved = async (tv: PairedTv) => {
    setReconnectingId(tv.id);
    setActionError(null);
    try {
      await remoteService.connectTv(tv);
      await refreshConnection();
      await refreshSaved();
      navigation.navigate('Remote');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to reconnect.';
      setActionError(message);
      if (/pairing required|enter.*(pin|code).*shown on the tv/i.test(message)) {
        navigation.navigate('Pairing', {
          deviceId: tv.id,
          name: tv.name,
          brand: tv.brand,
          ip: tv.ip,
        });
      } else {
        navigation.navigate('ConnectionError', {message});
      }
    } finally {
      setReconnectingId(null);
    }
  };

  const removeSaved = async (tv: PairedTv) => {
    try {
      setSavedTvs(await removePairedDevice(tv.id));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Could not remove the TV.');
    }
  };

  return (
    <ScrollView style={commonStyles.screen} contentContainerStyle={styles.content}>
      <Text style={commonStyles.title}>Home</Text>
      {loading ? (
        <Text style={commonStyles.emptyText}>Loading…</Text>
      ) : connectedTv ? (
        <View style={[commonStyles.card, styles.card]}>
          <View style={styles.cardHeader}>
            <View>
              <Text style={styles.tvName}>{connectedTv.name || 'Unknown TV'}</Text>
              <Text style={styles.tvDetail}>
                {getBrandMeta(connectedTv.brand).displayName}
                {connectedTv.model ? ` · ${connectedTv.model}` : ''} · {connectedTv.ip}
              </Text>
            </View>
            <ConnectionBadge connected />
          </View>
          <View style={styles.quickRow}>
            <ControlButton label="⏻ Power" onPress={() => void quick('power')} />
            <ControlButton label="Mute" onPress={() => void quick('mute')} />
            <ControlButton label="Vol −" onPress={() => void quick('volume-down')} />
            <ControlButton label="Vol +" onPress={() => void quick('volume-up')} />
          </View>
          {actionError ? <Text style={commonStyles.errorText}>{actionError}</Text> : null}
          <View style={styles.actions}>
            <ControlButton label="Open Remote" variant="primary" onPress={() => navigation.navigate('Remote')} />
            <ControlButton label="Streaming" onPress={() => navigation.navigate('Streaming')} />
          </View>
          <ControlButton
            label={disconnecting ? 'Disconnecting…' : 'Disconnect'}
            onPress={() => void onDisconnect()}
            disabled={disconnecting}
          />
        </View>
      ) : (
        <View style={[commonStyles.card, styles.card]}>
          <Text style={styles.tvName}>No TV connected</Text>
          <Text style={commonStyles.subtitle}>
            Discover a TV on your Wi-Fi, or reconnect a saved one.
          </Text>
          {error ? <Text style={commonStyles.errorText}>{error}</Text> : null}
          <View style={styles.actions}>
            <ControlButton label="Find my TV" variant="primary" onPress={() => navigation.navigate('Discovery')} />
            <ControlButton label="My saved TVs" onPress={() => navigation.navigate('ConnectTV')} />
          </View>
        </View>
      )}

      <Text style={commonStyles.sectionTitle}>Saved TVs</Text>
      {savedLoading ? (
        <Text style={commonStyles.emptyText}>Loading saved TVs…</Text>
      ) : savedTvs.length === 0 ? (
        <Text style={commonStyles.emptyText}>
          No saved TVs yet. Discover a TV on your Wi-Fi to save one here.
        </Text>
      ) : (
        savedTvs.map(tv => (
          <View key={tv.id}>
            <DeviceListItem
              tv={tv}
              onPress={() => void reconnectSaved(tv)}
              selected={reconnectingId === tv.id}
            />
            <View style={styles.savedActions}>
              <ControlButton
                label={reconnectingId === tv.id ? 'Connecting…' : 'Reconnect'}
                onPress={() => void reconnectSaved(tv)}
                disabled={reconnectingId === tv.id}
              />
              <ControlButton label="Remove" onPress={() => void removeSaved(tv)} />
            </View>
          </View>
        ))
      )}
      {actionError ? <Text style={commonStyles.errorText}>{actionError}</Text> : null}

      <Text style={commonStyles.sectionTitle}>Network</Text>
      <NetworkStatusCard
        networkInfo={networkInfo}
        backendStatus={backendStatus}
        tvIp={connectedTv?.ip ?? null}
        tvConnected={Boolean(connectedTv)}
        error={netError}
      />
      <View style={styles.footer}>
        <ControlButton label="Network details" onPress={() => navigation.navigate('NetworkInfo')} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {paddingBottom: 32, paddingTop: 16},
  card: {marginTop: 16, gap: 12},
  cardHeader: {flexDirection: 'row', justifyContent: 'space-between', gap: 12},
  tvName: {color: colors.text, fontSize: 20, fontWeight: '700'},
  tvDetail: {color: colors.textSecondary, fontSize: 14, marginTop: 4},
  quickRow: {flexDirection: 'row', gap: 10, flexWrap: 'wrap'},
  actions: {gap: 10},
  savedActions: {flexDirection: 'row', gap: 10, marginBottom: 16},
  footer: {marginTop: 16},
});
