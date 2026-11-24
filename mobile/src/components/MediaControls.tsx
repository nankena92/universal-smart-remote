import React from 'react';
import {StyleSheet, View} from 'react-native';
import ControlButton from './ControlButton';

interface MediaControlsProps {
  onPlay: () => void;
  onPause: () => void;
  onStop: () => void;
  onRewind: () => void;
  onFastForward: () => void;
  disabled?: boolean;
  supported?: boolean;
}

export default function MediaControls({
  onPlay,
  onPause,
  onStop,
  onRewind,
  onFastForward,
  disabled = false,
  supported = true,
}: MediaControlsProps) {
  const isDisabled = disabled || !supported;
  const disabledLabel = supported ? undefined : 'not supported on this TV';
  return (
    <View style={styles.container}>
      <ControlButton label="⏮" onPress={onRewind} disabled={isDisabled} disabledLabel={disabledLabel} accessibilityLabel="Rewind" />
      <ControlButton label="▶" onPress={onPlay} disabled={isDisabled} disabledLabel={disabledLabel} accessibilityLabel="Play" />
      <ControlButton label="⏸" onPress={onPause} disabled={isDisabled} disabledLabel={disabledLabel} accessibilityLabel="Pause" />
      <ControlButton label="⏹" onPress={onStop} disabled={isDisabled} disabledLabel={disabledLabel} accessibilityLabel="Stop" />
      <ControlButton label="⏭" onPress={onFastForward} disabled={isDisabled} disabledLabel={disabledLabel} accessibilityLabel="Fast forward" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flexDirection: 'row', gap: 10, justifyContent: 'center', flexWrap: 'wrap'},
});
