import React, {useEffect, useState} from 'react';
import {Alert, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {Settings} from '../types';
import {DEFAULT_SETTINGS} from '../types';
import {forgetAllPairedDevices, loadSettings, saveSettings} from '../utils/storage';
import {checkHealth} from '../services/api';
import ControlButton from '../components/ControlButton';

interface Props {
  navigation: any;
}

export default function SettingsScreen({navigation}: Props) {
  const [settings, setSettings] = useState<Settings>({...DEFAULT_SETTINGS});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<string | null>(null);

  useEffect(() => {
    void loadSettings()
      .then(setSettings)
      .catch(err => setError(err instanceof Error ? err.message : 'Could not load settings.'))
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const cleaned: Settings = {
        mode: settings.mode,
        backendUrl: settings.backendUrl.trim().replace(/\/+$/, '') || DEFAULT_SETTINGS.backendUrl,
        apiKey: settings.apiKey.trim(),
      };
      await saveSettings(cleaned);
      setSettings(cleaned);
      setMessage('Settings saved.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save settings.');
    } finally {
      setSaving(false);
    }
  };

  const testBackend = async () => {
    setBackendStatus('Checking…');
    try {
      const result = await checkHealth();
      setBackendStatus(
        result.success
          ? `Backend reachable at ${settings.backendUrl}.`
          : `Backend unreachable: ${result.error ?? 'unknown error'}`,
      );
    } catch (err) {
      setBackendStatus(`Backend unreachable: ${err instanceof Error ? err.message : 'unknown error'}`);
    }
  };

  const forget = () => {
    Alert.alert('Forget all paired TVs?', 'All saved TVs will be removed from this phone.', [
      {text: 'Cancel', style: 'cancel'},
      {
        text: 'Forget all',
        style: 'destructive',
        onPress: () => {
          void forgetAllPairedDevices()
            .then(() => setMessage('All paired TVs forgotten.'))
            .catch(err => setError(err instanceof Error ? err.message : 'Could not forget paired TVs.'));
        },
      },
    ]);
  };

  if (loading) {
    return (
      <View style={commonStyles.screenCentered}>
        <Text style={commonStyles.emptyText}>Loading settings…</Text>
      </View>
    );
  }

  return (
    <ScrollView style={commonStyles.screen} contentContainerStyle={styles.content}>
      <Text style={commonStyles.title}>Settings</Text>

      <Text style={commonStyles.sectionTitle}>Control mode</Text>
      <View style={styles.row}>
        <ControlButton
          label="Backend"
          variant={settings.mode === 'backend' ? 'primary' : 'default'}
          onPress={() => setSettings((s: Settings) => ({...s, mode: 'backend'}))}
        />
        <ControlButton
          label="Direct"
          variant={settings.mode === 'direct' ? 'primary' : 'default'}
          onPress={() => setSettings((s: Settings) => ({...s, mode: 'direct'}))}
        />
      </View>
      <Text style={styles.hint}>
        {settings.mode === 'backend'
          ? 'Commands go to the FastAPI backend on your network (all brands).'
          : 'Commands go straight from the phone to the TV. Only Roku, Samsung and LG are supported in direct mode.'}
      </Text>

      <Text style={commonStyles.sectionTitle}>Backend</Text>
      <View style={commonStyles.card}>
        <Text style={styles.label}>Backend URL</Text>
        <TextInput
          style={styles.input}
          value={settings.backendUrl}
          onChangeText={(v: string) => setSettings((s: Settings) => ({...s, backendUrl: v}))}
          placeholder="http://192.168.1.100:8000"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        <Text style={styles.label}>API key (X-API-Key)</Text>
        <TextInput
          style={styles.input}
          value={settings.apiKey}
          onChangeText={(v: string) => setSettings((s: Settings) => ({...s, apiKey: v}))}
          placeholder="Leave empty if the backend has no key set"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
        />
        <View style={styles.actions}>
          <ControlButton label={saving ? 'Saving…' : 'Save settings'} variant="primary" onPress={() => void save()} disabled={saving} />
          <ControlButton label="Test backend connection" onPress={() => void testBackend()} />
        </View>
        {backendStatus ? <Text style={styles.status}>{backendStatus}</Text> : null}
      </View>

      {message ? <Text style={styles.saved}>{message}</Text> : null}
      {error ? <Text style={[commonStyles.errorText, styles.error]}>{error}</Text> : null}

      <Text style={commonStyles.sectionTitle}>Paired TVs</Text>
      <ControlButton label="Forget all paired TVs" onPress={forget} />

      <Text style={commonStyles.sectionTitle}>About</Text>
      <View style={commonStyles.card}>
        <Text style={styles.about}>Universal Smart Remote · v1.0.0</Text>
        <Text style={styles.aboutDetail}>
          Local Wi-Fi only. Your TV and phone must be on the same network.
          The app never uses the cloud and never forwards ports.
        </Text>
        <Text style={styles.aboutDetail}>
          Samsung and LG direct control, and some other brand features, need
          on-device verification with a real TV (see the direct client source
          notes).
        </Text>
      </View>
      <View style={styles.footer}>
        <ControlButton label="Back to Home" onPress={() => navigation.navigate('Home')} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {paddingBottom: 32, paddingTop: 16},
  row: {flexDirection: 'row', gap: 12, marginTop: 8},
  hint: {color: colors.textSecondary, fontSize: 13, lineHeight: 18, marginTop: 8},
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
  actions: {gap: 10, marginTop: 16},
  status: {color: colors.textSecondary, fontSize: 14, marginTop: 12},
  saved: {color: colors.success, fontSize: 14, marginTop: 12},
  error: {marginTop: 12},
  about: {color: colors.text, fontSize: 15, fontWeight: '600'},
  aboutDetail: {color: colors.textSecondary, fontSize: 13, lineHeight: 18, marginTop: 6},
  footer: {marginTop: 16},
});
