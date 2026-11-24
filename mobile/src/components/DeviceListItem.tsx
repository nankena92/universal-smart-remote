import React from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {DiscoveredTv} from '../types';
import {getBrandMeta} from '../adapters/brandMeta';

interface DeviceListItemProps {
  tv: DiscoveredTv;
  onPress: (tv: DiscoveredTv) => void;
  selected?: boolean;
}

export default function DeviceListItem({tv, onPress, selected = false}: DeviceListItemProps) {
  const brand = getBrandMeta(tv.brand);
  return (
    <Pressable
      onPress={() => onPress(tv)}
      style={({pressed}: {pressed: boolean}) => [
        commonStyles.card,
        styles.item,
        selected && styles.selected,
        pressed && styles.pressed,
      ]}
      accessibilityRole="button"
      accessibilityLabel={`${tv.name}, ${brand.displayName}, ${tv.ip}`}>
      <View style={styles.main}>
        <Text style={styles.name}>{tv.name || 'Unknown TV'}</Text>
        <Text style={styles.detail}>
          {brand.displayName}
          {tv.model ? ` · ${tv.model}` : ''}
        </Text>
        <Text style={styles.detail}>
          {tv.ip}
          {tv.port ? `:${tv.port}` : ''}
          {tv.source ? ` · ${tv.source}` : ''}
        </Text>
      </View>
      <View style={styles.status}>
        <Text style={[styles.statusText, tv.paired ? styles.paired : styles.unpaired]}>
          {tv.paired ? 'Paired' : 'Not paired'}
        </Text>
        <Text style={styles.chevron}>›</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  item: {flexDirection: 'row', alignItems: 'center', marginBottom: 12},
  selected: {borderColor: colors.accent, borderWidth: 2},
  pressed: {opacity: 0.8},
  main: {flex: 1},
  name: {color: colors.text, fontSize: 17, fontWeight: '600'},
  detail: {color: colors.textSecondary, fontSize: 13, marginTop: 2},
  status: {alignItems: 'flex-end'},
  statusText: {fontSize: 12, fontWeight: '600'},
  paired: {color: colors.success},
  unpaired: {color: colors.textMuted},
  chevron: {color: colors.textMuted, fontSize: 24, marginTop: 4},
});
