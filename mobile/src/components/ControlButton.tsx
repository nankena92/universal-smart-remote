import React from 'react';
import {Pressable, StyleSheet, Text} from 'react-native';
import {colors, sizes} from '../theme';

interface ControlButtonProps {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  /** Shown instead of the label when disabled, e.g. "not supported on this TV". */
  disabledLabel?: string;
  variant?: 'default' | 'primary' | 'danger';
  accessibilityLabel?: string;
}

export default function ControlButton({
  label,
  onPress,
  disabled = false,
  disabledLabel,
  variant = 'default',
  accessibilityLabel,
}: ControlButtonProps) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({pressed}: {pressed: boolean}) => [
        styles.button,
        variant === 'primary' && styles.primary,
        variant === 'danger' && styles.danger,
        pressed && !disabled && styles.pressed,
        disabled && styles.disabled,
      ]}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{disabled}}>
      <Text style={[styles.label, disabled && styles.labelDisabled]}>
        {disabled && disabledLabel ? disabledLabel : label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: sizes.minTouch,
    minWidth: sizes.minTouch,
    paddingHorizontal: 16,
    borderRadius: sizes.buttonRadius,
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primary: {backgroundColor: colors.accent, borderColor: colors.accent},
  danger: {backgroundColor: '#3A1A1A', borderColor: colors.error},
  pressed: {opacity: 0.75},
  disabled: {opacity: 0.45},
  label: {color: colors.text, fontSize: 16, fontWeight: '600'},
  labelDisabled: {fontSize: 12, fontWeight: '400', color: colors.textSecondary},
});
