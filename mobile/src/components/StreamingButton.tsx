import React from 'react';
import {Pressable, StyleSheet, Text} from 'react-native';
import {colors, sizes} from '../theme';
import {StreamingAppId} from '../types';

// Text-based branding only — no trademarked image assets.
const APP_STYLES: Record<StreamingAppId, {label: string; backgroundColor: string}> = {
  netflix: {label: 'Netflix', backgroundColor: colors.netflix},
  prime: {label: 'Prime Video', backgroundColor: colors.primeVideo},
  youtube: {label: 'YouTube', backgroundColor: colors.youtube},
  disney: {label: 'Disney+', backgroundColor: colors.disney},
};

interface StreamingButtonProps {
  app: StreamingAppId;
  onPress: () => void;
  disabled?: boolean;
  supported?: boolean;
  loading?: boolean;
}

export default function StreamingButton({
  app,
  onPress,
  disabled = false,
  supported = true,
  loading = false,
}: StreamingButtonProps) {
  const style = APP_STYLES[app];
  const isDisabled = disabled || !supported || loading;
  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      style={({pressed}: {pressed: boolean}) => [
        styles.button,
        {backgroundColor: style.backgroundColor},
        pressed && !isDisabled && styles.pressed,
        isDisabled && styles.disabled,
      ]}
      accessibilityRole="button"
      accessibilityLabel={supported ? `Open ${style.label}` : `${style.label} not supported on this TV`}
      accessibilityState={{disabled: isDisabled}}>
      <Text style={styles.label}>{loading ? 'Opening…' : style.label}</Text>
      {!supported ? (
        <Text style={styles.unsupported}>not supported on this TV</Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 72,
    borderRadius: sizes.buttonRadius,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  pressed: {opacity: 0.8},
  disabled: {opacity: 0.45},
  label: {color: '#FFFFFF', fontSize: 20, fontWeight: '800'},
  unsupported: {color: '#FFFFFF', fontSize: 12, marginTop: 4, opacity: 0.9},
});
