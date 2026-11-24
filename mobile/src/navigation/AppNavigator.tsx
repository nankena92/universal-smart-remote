// React Navigation stack for all 10 screens.
import React from 'react';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import {colors} from '../theme';
import WelcomeScreen from '../screens/WelcomeScreen';
import HomeScreen from '../screens/HomeScreen';
import ConnectTvScreen from '../screens/ConnectTvScreen';
import DiscoveryScreen from '../screens/DiscoveryScreen';
import PairingScreen from '../screens/PairingScreen';
import RemoteScreen from '../screens/RemoteScreen';
import StreamingScreen from '../screens/StreamingScreen';
import SettingsScreen from '../screens/SettingsScreen';
import NetworkInfoScreen from '../screens/NetworkInfoScreen';
import ConnectionErrorScreen from '../screens/ConnectionErrorScreen';

export type RootStackParamList = {
  Welcome: undefined;
  Home: undefined;
  ConnectTV: undefined;
  Discovery: undefined;
  Pairing: {deviceId?: string; name?: string; brand?: string; ip?: string} | undefined;
  Remote: undefined;
  Streaming: undefined;
  Settings: undefined;
  NetworkInfo: undefined;
  ConnectionError: {message?: string} | undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();

export default function AppNavigator() {
  return (
    <Stack.Navigator
      initialRouteName="Welcome"
      screenOptions={{
        headerStyle: {backgroundColor: colors.background},
        headerTintColor: colors.text,
        headerTitleStyle: {fontWeight: '700'},
        contentStyle: {backgroundColor: colors.background},
      }}>
      <Stack.Screen name="Welcome" component={WelcomeScreen} options={{title: 'Smart Remote'}} />
      <Stack.Screen name="Home" component={HomeScreen} options={{title: 'Home'}} />
      <Stack.Screen name="ConnectTV" component={ConnectTvScreen} options={{title: 'Connect TV'}} />
      <Stack.Screen name="Discovery" component={DiscoveryScreen} options={{title: 'Discover TVs'}} />
      <Stack.Screen name="Pairing" component={PairingScreen} options={{title: 'Pair TV'}} />
      <Stack.Screen name="Remote" component={RemoteScreen} options={{title: 'Remote'}} />
      <Stack.Screen name="Streaming" component={StreamingScreen} options={{title: 'Streaming'}} />
      <Stack.Screen name="Settings" component={SettingsScreen} options={{title: 'Settings'}} />
      <Stack.Screen name="NetworkInfo" component={NetworkInfoScreen} options={{title: 'Network Info'}} />
      <Stack.Screen
        name="ConnectionError"
        component={ConnectionErrorScreen}
        options={{title: 'Connection Error'}}
      />
    </Stack.Navigator>
  );
}
