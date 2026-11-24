import React from 'react';
import {StyleSheet, Text, View} from 'react-native';
import {colors} from '../theme';

interface ConnectionBadgeProps {
  connected: boolean;
  label?: string;
}

export default function ConnectionBadge({connected, label}: ConnectionBadgeProps) {
  return (
    <View style={[styles.badge, connected ? styles.connected : styles.disconnected]}>
      <View style={[styles.dot, connected ? styles.dotConnected : styles.dotDisconnected]} />
      <Text style={styles.text}>{label ?? (connected ? 'Connected' : 'Disconnected')}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    gap: 6,
  },
  connected: {backgroundColor: 'rgba(34,197,94,0.15)'},
  disconnected: {backgroundColor: 'rgba(239,68,68,0.15)'},
  dot: {width: 8, height: 8, borderRadius: 4},
  dotConnected: {backgroundColor: colors.success},
  dotDisconnected: {backgroundColor: colors.error},
  text: {color: colors.text, fontSize: 13, fontWeight: '600'},
});
