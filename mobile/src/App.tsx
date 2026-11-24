import React, {useEffect} from 'react';
import {StatusBar} from 'react-native';
import {NavigationContainer} from '@react-navigation/native';
import {SafeAreaProvider} from 'react-native-safe-area-context';
import AppNavigator from './navigation/AppNavigator';
import {remoteService} from './services/remote';
import {colors} from './theme';

export default function App() {
  useEffect(() => {
    // Restore the last connected TV (if any) so Home/Remote can show it.
    void remoteService.restoreConnectedTv().catch(() => undefined);
  }, []);

  return (
    <SafeAreaProvider>
      <StatusBar barStyle="light-content" backgroundColor={colors.background} />
      <NavigationContainer>
        <AppNavigator />
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
