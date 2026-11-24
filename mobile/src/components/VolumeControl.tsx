import React from 'react';
import {StyleSheet, Text, View} from 'react-native';
import {colors} from '../theme';
import ControlButton from './ControlButton';

interface VolumeControlProps {
  onVolumeUp: () => void;
  onVolumeDown: () => void;
  onMute: () => void;
  disabled?: boolean;
  muted?: boolean;
}

export default function VolumeControl({
  onVolumeUp,
  onVolumeDown,
  onMute,
  disabled = false,
  muted = false,
}: VolumeControlProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Volume</Text>
      <View style={styles.row}>
        <ControlButton label="−" onPress={onVolumeDown} disabled={disabled} accessibilityLabel="Volume down" />
        <ControlButton
          label={muted ? 'Unmute' : 'Mute'}
          onPress={onMute}
          disabled={disabled}
          accessibilityLabel={muted ? 'Unmute' : 'Mute'}
        />
        <ControlButton label="+" onPress={onVolumeUp} disabled={disabled} accessibilityLabel="Volume up" />
      </View>
      {muted ? <Text style={styles.muted}>Muted</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {alignItems: 'center'},
  title: {color: colors.textSecondary, fontSize: 14, fontWeight: '600', marginBottom: 8},
  row: {flexDirection: 'row', gap: 12},
  muted: {color: colors.warning, fontSize: 13, marginTop: 6},
});
