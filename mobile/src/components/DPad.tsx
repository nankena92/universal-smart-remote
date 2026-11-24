import React, {useState} from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';
import {colors, sizes} from '../theme';
import {RemoteKey} from '../types';

interface DPadProps {
  onPress: (key: RemoteKey) => void;
  disabled?: boolean;
}

export default function DPad({onPress, disabled = false}: DPadProps) {
  const [pressed, setPressed] = useState<string | null>(null);

  const renderButton = (key: RemoteKey, label: string, style: object) => (
    <Pressable
      key={key}
      disabled={disabled}
      onPress={() => onPress(key)}
      onPressIn={() => setPressed(key)}
      onPressOut={() => setPressed(null)}
      style={[
        styles.button,
        style,
        pressed === key && styles.buttonPressed,
        disabled && styles.buttonDisabled,
      ]}
      accessibilityRole="button"
      accessibilityLabel={label}>
      <Text style={styles.label}>{label}</Text>
    </Pressable>
  );

  return (
    <View style={styles.container} accessibilityLabel="Directional pad">
      {renderButton('up', '▲', styles.up)}
      {renderButton('left', '◀', styles.left)}
      {renderButton('right', '▶', styles.right)}
      {renderButton('down', '▼', styles.down)}
      <Pressable
        disabled={disabled}
        onPress={() => onPress('ok')}
        onPressIn={() => setPressed('ok')}
        onPressOut={() => setPressed(null)}
        style={[
          styles.okButton,
          pressed === 'ok' && styles.buttonPressed,
          disabled && styles.buttonDisabled,
        ]}
        accessibilityRole="button"
        accessibilityLabel="OK">
        <Text style={styles.okLabel}>OK</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    width: 240,
    height: 240,
    borderRadius: 120,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    alignSelf: 'center',
    position: 'relative',
  },
  button: {
    position: 'absolute',
    width: sizes.dpadButton,
    height: sizes.dpadButton,
    borderRadius: sizes.dpadButton / 2,
    backgroundColor: colors.surfaceElevated,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPressed: {backgroundColor: colors.accent},
  buttonDisabled: {opacity: 0.4},
  label: {color: colors.text, fontSize: 20},
  up: {top: 8, left: 88},
  down: {bottom: 8, left: 88},
  left: {left: 8, top: 88},
  right: {right: 8, top: 88},
  okButton: {
    position: 'absolute',
    width: sizes.dpadCenter,
    height: sizes.dpadCenter,
    borderRadius: sizes.dpadCenter / 2,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    top: 82,
    left: 82,
  },
  okLabel: {color: colors.text, fontSize: 18, fontWeight: '700'},
});
