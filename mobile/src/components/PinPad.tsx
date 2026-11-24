import React, {useState} from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';
import {colors, sizes} from '../theme';

interface PinPadProps {
  length?: number;
  onSubmit: (pin: string) => void;
  disabled?: boolean;
}

export default function PinPad({length = 4, onSubmit, disabled = false}: PinPadProps) {
  const [pin, setPin] = useState('');

  const addDigit = (digit: string) => {
    if (disabled || pin.length >= length) {
      return;
    }
    const next = pin + digit;
    setPin(next);
    if (next.length === length) {
      onSubmit(next);
    }
  };

  const backspace = () => {
    if (disabled) {
      return;
    }
    setPin((p: string) => p.slice(0, -1));
  };

  const clear = () => {
    if (disabled) {
      return;
    }
    setPin('');
  };

  const dots = Array.from({length}, (_, i) => (
    <View key={i} style={[styles.dot, i < pin.length && styles.dotFilled]} />
  ));

  const keys: (string | 'back' | 'clear')[] = [
    '1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back',
  ];

  return (
    <View style={styles.container}>
      <View style={styles.dots}>{dots}</View>
      <Text style={styles.hint}>Enter the PIN shown on your TV</Text>
      <View style={styles.grid}>
        {keys.map(key => {
          const label = key === 'back' ? '⌫' : key === 'clear' ? 'C' : key;
          return (
            <Pressable
              key={String(key)}
              disabled={disabled}
              onPress={() => {
                if (key === 'back') {
                  backspace();
                } else if (key === 'clear') {
                  clear();
                } else {
                  addDigit(key);
                }
              }}
              style={({pressed}: {pressed: boolean}) => [
                styles.key,
                pressed && !disabled && styles.keyPressed,
                disabled && styles.keyDisabled,
              ]}
              accessibilityRole="button"
              accessibilityLabel={key === 'back' ? 'Delete' : key === 'clear' ? 'Clear' : `Digit ${key}`}>
              <Text style={styles.keyLabel}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {alignItems: 'center'},
  dots: {flexDirection: 'row', gap: 12, marginBottom: 8},
  dot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: colors.accent,
  },
  dotFilled: {backgroundColor: colors.accent},
  hint: {color: colors.textSecondary, fontSize: 14, marginBottom: 16},
  grid: {flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 12, maxWidth: 300},
  key: {
    width: 72,
    height: sizes.minTouch,
    borderRadius: sizes.buttonRadius,
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  keyPressed: {backgroundColor: colors.accent},
  keyDisabled: {opacity: 0.4},
  keyLabel: {color: colors.text, fontSize: 22, fontWeight: '600'},
});
