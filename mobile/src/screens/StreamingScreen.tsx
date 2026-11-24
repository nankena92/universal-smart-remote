import React, {useEffect, useState} from 'react';
import {ScrollView, StyleSheet, Text, View} from 'react-native';
import {commonStyles} from '../theme';
import {ConnectionMode, StreamingAppId} from '../types';
import {STREAMING_APPS, getBrandMeta, isAppSupportedOnBrand} from '../adapters/brandMeta';
import {useTvConnection} from '../hooks/useTvConnection';
import {remoteService} from '../services/remote';
import {loadSettings} from '../utils/storage';
import StreamingButton from '../components/StreamingButton';
import ControlButton from '../components/ControlButton';
import ConnectionBadge from '../components/ConnectionBadge';

interface Props {
  navigation: any;
}

export default function StreamingScreen({navigation}: Props) {
  const {connectedTv, loading} = useTvConnection();
  const [launching, setLaunching] = useState<StreamingAppId | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [launched, setLaunched] = useState<string | null>(null);
  const [mode, setMode] = useState<ConnectionMode>('backend');

  useEffect(() => {
    void loadSettings().then(s => setMode(s.mode));
  }, []);

  const launch = async (app: StreamingAppId) => {
    if (!connectedTv) {
      setError('No TV is connected. Connect to a TV first.');
      return;
    }
    setLaunching(app);
    setError(null);
    setLaunched(null);
    try {
      await remoteService.launchApp(app);
      setLaunched(`${app} launch command sent to ${connectedTv.name || connectedTv.ip}.`);
    } catch (err) {
      const message = err instanceof Error ? err.message : `Failed to launch ${app}.`;
      setError(message);
      if (message.includes('same local Wi-Fi')) {
        navigation.navigate('ConnectionError', {message});
      }
    } finally {
      setLaunching(null);
    }
  };

  // In backend mode the backend is the authority on whether an app can
  // launch (its adapters decide per brand and per host, e.g. Android TV
  // needs ADB, TCL delegates, Sony is unsupported) and reports failures
  // honestly — so every button is attemptable and a failure shows the
  // backend's real error. In direct mode the phone's static app-id table
  // is the authority, so unsupported brands stay disabled.
  const isSupported = (app: StreamingAppId): boolean =>
    mode === 'backend' ? true : isAppSupportedOnBrand(app, connectedTv?.brand);

  return (
    <ScrollView style={commonStyles.screen} contentContainerStyle={styles.content}>
      <Text style={commonStyles.title}>Streaming</Text>
      {loading ? (
        <Text style={commonStyles.emptyText}>Loading…</Text>
      ) : !connectedTv ? (
        <View style={commonStyles.card}>
          <Text style={commonStyles.subtitle}>No TV is connected.</Text>
          <View style={styles.actions}>
            <ControlButton label="Find my TV" variant="primary" onPress={() => navigation.navigate('Discovery')} />
          </View>
        </View>
      ) : (
        <>
          <View style={styles.header}>
            <Text style={styles.tvName}>
              {connectedTv.name || 'Unknown TV'} · {getBrandMeta(connectedTv.brand).displayName}
            </Text>
            <ConnectionBadge connected />
          </View>
          <View style={styles.list}>
            {STREAMING_APPS.map(app => (
              <StreamingButton
                key={app.id}
                app={app.id}
                supported={isSupported(app.id)}
                loading={launching === app.id}
                onPress={() => void launch(app.id)}
              />
            ))}
          </View>
          {launched ? <Text style={styles.launched}>{launched}</Text> : null}
          {error ? <Text style={[commonStyles.errorText, styles.error]}>{error}</Text> : null}
          <Text style={styles.note}>
            {mode === 'backend'
              ? 'In backend mode the backend checks whether the app is supported on this TV and reports any problem honestly.'
              : 'Launch is only attempted when the app is supported on this TV brand. For Roku, the app must also be installed — the app checks that first and reports it honestly if it is not.'}
          </Text>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {paddingBottom: 32, paddingTop: 16},
  header: {marginTop: 16, gap: 8},
  tvName: {color: '#FFFFFF', fontSize: 16, fontWeight: '600'},
  list: {gap: 12, marginTop: 16},
  actions: {marginTop: 16},
  launched: {color: '#22C55E', fontSize: 14, marginTop: 16},
  error: {marginTop: 16},
  note: {color: '#6B6B7E', fontSize: 13, lineHeight: 18, marginTop: 16},
});
