import React from 'react';
import {StyleSheet, Text, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import ControlButton from '../components/ControlButton';

interface Props {
  navigation: any;
}

export default function WelcomeScreen({navigation}: Props) {
  return (
    <View style={commonStyles.screenCentered}>
      <Text style={styles.logo}>📺</Text>
      <Text style={commonStyles.title}>Universal Smart Remote</Text>
      <Text style={[commonStyles.subtitle, styles.subtitle]}>
        Control your Samsung, LG, Sony, Android TV, Google TV, TCL, Roku, or
        Fire TV — over your local Wi-Fi only. No cloud, no account.
      </Text>
      <View style={styles.actions}>
        <ControlButton label="Find my TV" variant="primary" onPress={() => navigation.navigate('Discovery')} />
        <ControlButton label="My saved TVs" onPress={() => navigation.navigate('ConnectTV')} />
        <ControlButton label="Settings" onPress={() => navigation.navigate('Settings')} />
      </View>
      <Text style={styles.note}>
        Your TV and phone must be on the same Wi-Fi network.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  logo: {fontSize: 56, marginBottom: 16},
  subtitle: {marginTop: 12, marginBottom: 24},
  actions: {gap: 12},
  note: {color: colors.textMuted, fontSize: 13, marginTop: 24, textAlign: 'center'},
});
