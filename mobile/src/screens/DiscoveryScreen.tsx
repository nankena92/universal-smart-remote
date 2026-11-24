import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {DiscoveredTv} from '../types';
import {addTvDiscoveredListener, isNativeModuleAvailable, startDiscovery, stopDiscovery} from '../services/native';
import {discoverDevices} from '../services/api';
import {loadSettings} from '../utils/storage';
import {isValidIp} from '../utils/network';
import {getBrandMeta, normaliseBrand} from '../adapters/brandMeta';
import {remoteService} from '../services/remote';
import DeviceListItem from '../components/DeviceListItem';
import ControlButton from '../components/ControlButton';

interface Props {
  navigation: any;
}

const MANUAL_BRANDS = ['samsung', 'lg', 'roku', 'sony', 'androidtv', 'googletv', 'tcl', 'firetv'];
// Native (SSDP/Bonjour) events keep arriving for a while after the backend
// sweep finishes; give them a short grace window, then stop discovery so
// the radios/scans do not run forever.
const NATIVE_GRACE_MS = 5000;

function isPairingRequired(message: string): boolean {
  return /pairing required|enter.*(pin|code).*shown on the tv/i.test(message);
}

export default function DiscoveryScreen({navigation}: Props) {
  const [tvs, setTvs] = useState<DiscoveredTv[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [manualIp, setManualIp] = useState('');
  const [manualName, setManualName] = useState('');
  const [manualBrand, setManualBrand] = useState('samsung');
  const mounted = useRef(true);
  const foundCount = useRef(0);

  const addTv = useCallback((tv: DiscoveredTv) => {
    if (!tv.ip) {
      return;
    }
    setTvs((prev: DiscoveredTv[]) => {
      const existing = prev.find((t: DiscoveredTv) => t.ip === tv.ip);
      if (!existing) {
        foundCount.current += 1;
        return [...prev, {...tv, id: tv.id || `discovered-${tv.ip}`}];
      }
      // Same TV seen from a second source (native + backend): merge,
      // preferring the record with real values and a paired flag.
      const merged: DiscoveredTv = {
        ...existing,
        name: existing.name || tv.name,
        brand: existing.brand && existing.brand !== 'unknown' ? existing.brand : tv.brand,
        model: existing.model || tv.model,
        port: existing.port || tv.port,
        mac: existing.mac || tv.mac,
        source: existing.source,
        paired: Boolean(existing.paired || tv.paired),
      };
      return prev.map((t: DiscoveredTv) => (t.ip === tv.ip ? merged : t));
    });
  }, []);

  const scan = useCallback(async () => {
    setScanning(true);
    setError(null);
    setTvs([]);
    foundCount.current = 0;
    let nativeError: string | null = null;
    let backendError: string | null = null;
    let backendMode = false;
    // Primary: native discovery (SSDP on Android, Bonjour/SSDP on iOS).
    if (isNativeModuleAvailable()) {
      try {
        await startDiscovery();
      } catch (err) {
        nativeError = err instanceof Error ? err.message : 'Native discovery failed.';
      }
    } else {
      nativeError =
        'Native discovery module is not available in this build. Trying the backend discovery scan instead.';
    }
    // Backend scan as a second source when in backend mode.
    try {
      const settings = await loadSettings();
      backendMode = settings.mode === 'backend';
      if (backendMode) {
        const result = await discoverDevices();
        if (result.success && result.data) {
          result.data.forEach(addTv);
        } else {
          backendError = result.error ?? 'Backend discovery failed.';
        }
      }
    } catch (err) {
      backendError = err instanceof Error ? err.message : 'Discovery failed.';
    }
    // Let late native events arrive, then stop the native scan.
    await new Promise(resolve => setTimeout(resolve, NATIVE_GRACE_MS));
    try {
      await stopDiscovery();
    } catch {
      // Discovery already stopped; nothing to report.
    }
    if (mounted.current) {
      // A source failing must not hide TVs the other source found.
      if (foundCount.current > 0) {
        setError(null);
      } else if (nativeError && backendError) {
        setError(`Discovery found nothing. Native: ${nativeError} Backend: ${backendError}`);
      } else if (backendMode && backendError) {
        setError(backendError);
      } else if (nativeError) {
        setError(nativeError);
      } else {
        setError(null);
      }
      setScanning(false);
    }
  }, [addTv]);

  useEffect(() => {
    mounted.current = true;
    let subscription: {remove(): void} | null = null;
    try {
      subscription = addTvDiscoveredListener(addTv);
    } catch {
      subscription = null;
    }
    void scan();
    return () => {
      mounted.current = false;
      subscription?.remove();
      void stopDiscovery().catch(() => undefined);
    };
  }, [addTv, scan]);

  const selectTv = async (tv: DiscoveredTv) => {
    setConnectingId(tv.id);
    setError(null);
    try {
      await remoteService.connectTv(tv);
      navigation.navigate('Remote');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to connect to the TV.';
      setError(message);
      if (isPairingRequired(message)) {
        // Android TV (and any brand whose connect reports it) shows a
        // pairing code on the TV; the PIN/code is entered on Pairing.
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

  const connectManual = async () => {
    if (!isValidIp(manualIp)) {
      setError('Enter a valid TV IP address, e.g. 192.168.1.42.');
      return;
    }
    const tv: DiscoveredTv = {
      id: `manual-${manualIp.trim()}`,
      name: manualName.trim() || `TV (${manualIp.trim()})`,
      brand: normaliseBrand(manualBrand),
      model: '',
      ip: manualIp.trim(),
      port: getBrandMeta(manualBrand).defaultPort,
      mac: '',
      source: 'manual',
      paired: false,
    };
    await selectTv(tv);
  };

  const showManualFallback = tvs.length === 0 && !scanning;

  return (
    <ScrollView style={commonStyles.screen} contentContainerStyle={styles.content}>
      <Text style={commonStyles.title}>Discover TVs</Text>
      <Text style={[commonStyles.subtitle, styles.sub]}>
        Scanning your local Wi-Fi for TVs. Make sure your TV is on and on the
        same network as this phone.
      </Text>
      <ControlButton
        label={scanning ? 'Scanning…' : 'Scan again'}
        variant="primary"
        onPress={() => void scan()}
        disabled={scanning}
      />
      {error ? <Text style={[commonStyles.errorText, styles.error]}>{error}</Text> : null}
      <Text style={commonStyles.sectionTitle}>
        {tvs.length === 0 && !scanning
          ? 'No TVs found'
          : `${tvs.length} TV${tvs.length === 1 ? '' : 's'} found`}
      </Text>
      {tvs.length === 0 && !scanning ? (
        <Text style={commonStyles.emptyText}>
          Nothing found. Check the TV is powered on, Wi-Fi is on, and both
          devices share the same network — then scan again, or add the TV
          manually below.
        </Text>
      ) : (
        tvs.map((tv: DiscoveredTv) => (
          <DeviceListItem
            key={tv.id}
            tv={tv}
            onPress={() => void selectTv(tv)}
            selected={connectingId === tv.id}
          />
        ))
      )}
      {connectingId ? <Text style={commonStyles.emptyText}>Connecting…</Text> : null}

      {showManualFallback ? (
        <View style={styles.manual}>
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
            <ControlButton
              label={connectingId ? 'Connecting…' : 'Connect'}
              variant="primary"
              onPress={() => void connectManual()}
              disabled={Boolean(connectingId)}
            />
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {paddingBottom: 32, paddingTop: 16},
  sub: {marginTop: 8, marginBottom: 16},
  error: {marginTop: 12},
  manual: {marginTop: 8},
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
});
