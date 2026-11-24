import React, {useCallback, useEffect, useState} from 'react';
import {Alert, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {DiscoveredTv, PairedTv} from '../types';
import {getBrandMeta, normaliseBrand} from '../adapters/brandMeta';
import {loadPairedDevices, loadSettings, removePairedDevice} from '../utils/storage';
import {listDevices} from '../services/api';
import {isValidIp} from '../utils/network';
import {remoteService} from '../services/remote';
import DeviceListItem from '../components/DeviceListItem';
import ControlButton from '../components/ControlButton';

interface Props {
  navigation: any;
}

const MANUAL_BRANDS = ['samsung', 'lg', 'roku', 'sony', 'androidtv', 'firetv', 'tcl'];

export default function ConnectTvScreen({navigation}: Props) {
  const [paired, setPaired] = useState<PairedTv[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [manualIp, setManualIp] = useState('');
  const [manualName, setManualName] = useState('');
  const [manualBrand, setManualBrand] = useState('samsung');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      // Saved TVs live in two places: on-phone storage and the backend's
      // SQLite DB (GET /devices). Merge both, deduped by IP, so a TV saved
      // by the backend (or on another phone using the same backend) shows
      // up here too. The backend record wins the id — it is the id the
      // backend's pair/disconnect calls need.
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
              } else {
                merged = merged.map(d =>
                  d.ip === saved.ip ? {...d, id: saved.id, paired: true} : d,
                );
              }
            }
          }
        }
      } catch {
        // Backend unreachable: local saved TVs are still usable.
      }
      setPaired(merged);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load saved TVs.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const reconnect = async (tv: DiscoveredTv) => {
    setConnectingId(tv.id);
    setError(null);
    try {
      await remoteService.connectTv(tv);
      navigation.navigate('Remote');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to reconnect.';
      setError(message);
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
      setConnectingId(null);
    }
  };

  const remove = (tv: PairedTv) => {
    // NOTE: the backend has no delete-saved-device endpoint, so removing
    // here only forgets the TV on this phone; its record stays in the
    // backend's saved-devices DB until the backend gains such an endpoint.
    Alert.alert('Remove TV?', `${tv.name} (${tv.ip}) will be forgotten on this phone.`, [
      {text: 'Cancel', style: 'cancel'},
      {
        text: 'Remove',
        style: 'destructive',
        onPress: () => {
          void removePairedDevice(tv.id).then(setPaired).catch(err => {
            setError(err instanceof Error ? err.message : 'Could not remove the TV.');
          });
        },
      },
    ]);
  };

  const connectManual = async () => {
    if (!isValidIp(manualIp)) {
      setError('Enter a valid TV IP address, e.g. 192.168.1.42.');
      return;
    }
    const tv: DiscoveredTv = {
      id: `manual-${manualIp}`,
      name: manualName.trim() || `TV (${manualIp})`,
      brand: normaliseBrand(manualBrand),
      model: '',
      ip: manualIp.trim(),
      port: getBrandMeta(manualBrand).defaultPort,
      mac: '',
      source: 'manual',
      paired: false,
    };
    await reconnect(tv);
  };

  return (
    <ScrollView style={commonStyles.screen} contentContainerStyle={styles.content}>
      <Text style={commonStyles.title}>Connect TV</Text>
      <Text style={[commonStyles.subtitle, styles.sub]}>Saved / paired TVs</Text>
      {loading ? (
        <Text style={commonStyles.emptyText}>Loading saved TVs…</Text>
      ) : paired.length === 0 ? (
        <Text style={commonStyles.emptyText}>
          No saved TVs yet. Discover a TV on your Wi-Fi, or add one manually below.
        </Text>
      ) : (
        paired.map((tv: PairedTv) => (
          <View key={tv.id}>
            <DeviceListItem tv={tv} onPress={() => void reconnect(tv)} selected={connectingId === tv.id} />
            <View style={styles.rowActions}>
              <ControlButton
                label={connectingId === tv.id ? 'Connecting…' : 'Reconnect'}
                onPress={() => void reconnect(tv)}
                disabled={connectingId === tv.id}
              />
              <ControlButton label="Remove" onPress={() => remove(tv)} />
            </View>
          </View>
        ))
      )}
      {error ? <Text style={[commonStyles.errorText, styles.error]}>{error}</Text> : null}

      <Text style={commonStyles.sectionTitle}>Add TV manually</Text>
      <View style={commonStyles.card}>
        <Text style={styles.label}>TV IP address</Text>
        <TextInput
          style={styles.input}
          value={manualIp}
          onChangeText={setManualIp}
          placeholder="192.168.1.42"
          placeholderTextColor={colors.textMuted}
          keyboardType="decimal-pad"
          autoCapitalize="none"
        />
        <Text style={styles.label}>Name (optional)</Text>
        <TextInput
          style={styles.input}
          value={manualName}
          onChangeText={setManualName}
          placeholder="Living room TV"
          placeholderTextColor={colors.textMuted}
        />
        <Text style={styles.label}>Brand</Text>
        <View style={styles.brandRow}>
          {MANUAL_BRANDS.map(b => (
            <ControlButton
              key={b}
              label={getBrandMeta(b).displayName}
              variant={manualBrand === b ? 'primary' : 'default'}
              onPress={() => setManualBrand(b)}
            />
          ))}
        </View>
        <ControlButton label="Connect" variant="primary" onPress={() => void connectManual()} />
      </View>
      <View style={styles.footer}>
        <ControlButton label="Discover TVs" onPress={() => navigation.navigate('Discovery')} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {paddingBottom: 32, paddingTop: 16},
  sub: {marginTop: 8, marginBottom: 16},
  rowActions: {flexDirection: 'row', gap: 10, marginBottom: 16},
  error: {marginTop: 12},
  label: {color: colors.textSecondary, fontSize: 14, marginBottom: 6, marginTop: 10},
  input: {
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    color: colors.text,
    minHeight: 56,
    paddingHorizontal: 14,
    fontSize: 16,
  },
  brandRow: {flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 16},
  footer: {marginTop: 16},
});
