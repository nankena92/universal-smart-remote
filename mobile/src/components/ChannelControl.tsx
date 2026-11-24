import React from 'react';
import {StyleSheet, Text, View} from 'react-native';
import {colors} from '../theme';
import ControlButton from './ControlButton';

interface ChannelControlProps {
  onChannelUp: () => void;
  onChannelDown: () => void;
  disabled?: boolean;
  supported?: boolean;
}

export default function ChannelControl({
  onChannelUp,
  onChannelDown,
  disabled = false,
  supported = true,
}: ChannelControlProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Channel</Text>
      <View style={styles.row}>
        <ControlButton
          label="CH −"
          onPress={onChannelDown}
          disabled={disabled || !supported}
          disabledLabel={supported ? undefined : 'not supported on this TV'}
          accessibilityLabel="Channel down"
        />
        <ControlButton
          label="CH +"
          onPress={onChannelUp}
          disabled={disabled || !supported}
          disabledLabel={supported ? undefined : 'not supported on this TV'}
          accessibilityLabel="Channel up"
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {alignItems: 'center'},
  title: {color: colors.textSecondary, fontSize: 14, fontWeight: '600', marginBottom: 8},
  row: {flexDirection: 'row', gap: 12},
});
