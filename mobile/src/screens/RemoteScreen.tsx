import React, {useEffect, useRef, useState} from 'react';
import {ScrollView, StyleSheet, Text, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {RemoteKey} from '../types';
import {getBrandMeta, unsupportedLabel} from '../adapters/brandMeta';
import {useTvConnection} from '../hooks/useTvConnection';
import {SAME_WIFI_ERROR} from '../types';
import DPad from '../components/DPad';
import ControlButton from '../components/ControlButton';
import VolumeControl from '../components/VolumeControl';
import ChannelControl from '../components/ChannelControl';
import MediaControls from '../components/MediaControls';
import ConnectionBadge from '../components/ConnectionBadge';

interface Props {
  navigation: any;
}

export default function RemoteScreen({navigation}: Props) {
  const {connectedTv, loading, error: connError, sendKey} = useTvConnection();
  const [toast, setToast] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (toastTimer.current) {
        clearTimeout(toastTimer.current);
      }
    };
  }, []);

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimer.current) {
      clearTimeout(toastTimer.current);
    }
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  };

  const press = async (key: RemoteKey) => {
    const ok = await sendKey(key);
    if (!ok) {
      // sendKey's error is in connError via the hook; surface it as a toast.
      showToast('Command failed. See below.');
      return;
    }
    if (key === 'mute') {
      setMuted((m: boolean) => !m);
    }
  };

  // Keep the latest hook error visible as a toast too.
  useEffect(() => {
    if (connError) {
      showToast(connError);
      if (connError.includes(SAME_WIFI_ERROR)) {
        navigation.navigate('ConnectionError', {message: connError});
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connError]);

  if (loading) {
    return (
      <View style={commonStyles.screenCentered}>
        <Text style={commonStyles.emptyText}>Loading…</Text>
      </View>
    );
  }

  if (!connectedTv) {
    return (
      <View style={commonStyles.screenCentered}>
        <Text style={commonStyles.title}>No TV connected</Text>
        <Text style={[commonStyles.subtitle, styles.sub]}>
          Connect to a TV before using the remote.
        </Text>
        <ControlButton label="Find my TV" variant="primary" onPress={() => navigation.navigate('Discovery')} />
      </View>
    );
  }

  const meta = getBrandMeta(connectedTv.brand);
  const f = meta.features;

  return (
    <ScrollView style={commonStyles.screen} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <View>
          <Text style={styles.tvName}>{connectedTv.name || 'Unknown TV'}</Text>
          <Text style={styles.tvDetail}>
            {meta.displayName} · {connectedTv.ip}
          </Text>
        </View>
        <ConnectionBadge connected />
      </View>

      <View style={styles.topRow}>
        <ControlButton
          label="⏻ Power"
          variant="danger"
          onPress={() => void press('power')}
          disabled={!f.power}
          disabledLabel={f.power ? undefined : unsupportedLabel('Power', connectedTv.brand)}
        />
        <ControlButton label="Settings" onPress={() => navigation.navigate('Settings')} />
      </View>

      <DPad onPress={key => void press(key)} />

      <View style={styles.row}>
        <ControlButton label="‹ Back" onPress={() => void press('back')} />
        <ControlButton label="Home" variant="primary" onPress={() => void press('home')} />
        <ControlButton
          label="Menu"
          onPress={() => void press('menu')}
          disabled={!f.power}
        />
      </View>

      <View style={styles.controlsRow}>
        <VolumeControl
          onVolumeUp={() => void press('volume-up')}
          onVolumeDown={() => void press('volume-down')}
          onMute={() => void press('mute')}
          disabled={!f.volume && !f.mute}
          muted={muted}
        />
        <ChannelControl
          onChannelUp={() => void press('channel-up')}
          onChannelDown={() => void press('channel-down')}
          supported={f.channel}
        />
      </View>
      {!f.volume ? (
        <Text style={styles.unsupported}>{unsupportedLabel('Volume', connectedTv.brand)}</Text>
      ) : null}

      <Text style={commonStyles.sectionTitle}>Media</Text>
      <MediaControls
        onPlay={() => void press('play')}
        onPause={() => void press('pause')}
        onStop={() => void press('stop')}
        onRewind={() => void press('rewind')}
        onFastForward={() => void press('fast-forward')}
        supported={f.media}
      />

      <View style={styles.footer}>
        <ControlButton label="Streaming apps" variant="primary" onPress={() => navigation.navigate('Streaming')} />
        <ControlButton label="Network info" onPress={() => navigation.navigate('NetworkInfo')} />
      </View>

      {toast ? (
        <View style={styles.toast}>
          <Text style={styles.toastText}>{toast}</Text>
        </View>
      ) : null}
      {connError ? <Text style={[commonStyles.errorText, styles.error]}>{connError}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {paddingBottom: 48, paddingTop: 16, gap: 16},
  header: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12},
  tvName: {color: colors.text, fontSize: 22, fontWeight: '700'},
  tvDetail: {color: colors.textSecondary, fontSize: 14, marginTop: 4},
  topRow: {flexDirection: 'row', justifyContent: 'space-between', gap: 12},
  row: {flexDirection: 'row', justifyContent: 'center', gap: 12},
  controlsRow: {flexDirection: 'row', justifyContent: 'space-around', flexWrap: 'wrap', gap: 16},
  unsupported: {color: colors.textMuted, fontSize: 13, textAlign: 'center'},
  footer: {gap: 10, marginTop: 8},
  sub: {marginTop: 12, marginBottom: 24},
  toast: {
    backgroundColor: colors.error,
    borderRadius: 12,
    padding: 12,
    marginTop: 8,
  },
  toastText: {color: colors.text, fontSize: 14, fontWeight: '600'},
  error: {marginTop: 8},
});
