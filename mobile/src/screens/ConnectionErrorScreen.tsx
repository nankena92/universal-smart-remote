import React from 'react';
import {StyleSheet, Text, View} from 'react-native';
import {SAME_WIFI_ERROR} from '../types';
import {commonStyles} from '../theme';
import ControlButton from '../components/ControlButton';

interface Props {
  navigation: any;
  route: {params?: {message?: string}};
}

export default function ConnectionErrorScreen({navigation, route}: Props) {
  const message = route.params?.message ?? SAME_WIFI_ERROR;
  return (
    <View style={commonStyles.screenCentered}>
      <Text style={styles.icon}>⚠</Text>
      <Text style={commonStyles.title}>Connection error</Text>
      <Text style={[commonStyles.subtitle, styles.message]}>{message}</Text>
      <Text style={styles.help}>
        Check that both devices are on the same Wi-Fi network, that the TV is
        powered on, and that the backend (if you use backend mode) is running
        on the same network.
      </Text>
      <View style={styles.actions}>
        <ControlButton label="Retry" variant="primary" onPress={() => navigation.goBack()} />
        <ControlButton label="Discover TVs again" onPress={() => navigation.navigate('Discovery')} />
        <ControlButton label="Network info" onPress={() => navigation.navigate('NetworkInfo')} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  icon: {fontSize: 48, marginBottom: 16, textAlign: 'center'},
  message: {marginTop: 12, marginBottom: 12},
  help: {color: '#A1A1B5', fontSize: 14, lineHeight: 20, marginBottom: 24},
  actions: {gap: 12},
});
