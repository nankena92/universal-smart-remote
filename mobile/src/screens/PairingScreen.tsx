import React, {useState} from 'react';
import {StyleSheet, Text, TextInput, View} from 'react-native';
import {colors, commonStyles} from '../theme';
import {remoteService} from '../services/remote';
import PinPad from '../components/PinPad';
import ControlButton from '../components/ControlButton';

interface Props {
  navigation: any;
  route: {params?: {deviceId?: string; name?: string; brand?: string; ip?: string}};
}

type PairingState = 'idle' | 'submitting' | 'success' | 'error';

// Android TV / Google TV show a 6-character HEXADECIMAL pairing code
// (letters A–F are possible), so the digit-only PinPad cannot enter it —
// those brands get a text field instead. Other brands use the 4-digit PIN
// pad; Samsung/LG normally pair with an on-TV Allow prompt, not a PIN.
function brandNeedsHexCode(brand: string): boolean {
  const b = brand.trim().toLowerCase();
  return b === 'androidtv' || b === 'googletv';
}

export default function PairingScreen({navigation, route}: Props) {
  const deviceId = route.params?.deviceId ?? '';
  const name = route.params?.name ?? 'TV';
  const brand = route.params?.brand ?? '';
  const ip = route.params?.ip ?? '';
  const needsHexCode = brandNeedsHexCode(brand);
  const [state, setState] = useState<PairingState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState('');

  const submitPin = async (pin: string) => {
    if (!deviceId && !ip) {
      setError('No TV was selected for pairing. Go back and pick a TV first.');
      setState('error');
      return;
    }
    if (needsHexCode && !/^[0-9a-fA-F]{6}$/.test(pin.trim())) {
      setError('The code is exactly 6 hexadecimal characters (0–9, A–F) as shown on the TV.');
      setState('error');
      return;
    }
    setState('submitting');
    setError(null);
    try {
      await remoteService.pairTv(deviceId, pin.trim(), ip || undefined);
      setState('success');
      navigation.navigate('Remote');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pairing failed. Check the PIN and try again.');
      setState('error');
    }
  };

  // The backend runs pairing on the adapter instance created by connect();
  // if that session has expired (or the TV was never saved), the backend
  // honestly reports "No pairing session is in progress" / "No device
  // found" — the fix is to connect again so the TV shows a fresh code,
  // then enter it before the session times out. Never bypass TV auth.
  const sessionExpiredHint =
    error !== null &&
    /no pairing session is in progress|no device found/i.test(error)
      ? 'The pairing session on the backend has expired (or this TV was never saved there). Go back, connect to the TV again so it shows a fresh code, then enter the new code here.'
      : null;

  return (
    <View style={commonStyles.screenCentered}>
      <Text style={commonStyles.title}>Pair with {name}</Text>
      <Text style={[commonStyles.subtitle, styles.sub]}>
        {brand ? `${brand} · ` : ''}
        {needsHexCode
          ? 'Enter the 6-character code shown on the TV screen.'
          : 'Enter the PIN shown on the TV screen. In direct mode, Samsung and LG pair with an on-screen Allow prompt instead of a PIN — if no PIN is shown, go back and connect again.'}
      </Text>
      {state === 'success' ? (
        <Text style={styles.success}>Paired successfully.</Text>
      ) : needsHexCode ? (
        <View style={styles.codeBox}>
          <TextInput
            style={styles.codeInput}
            value={code}
            onChangeText={setCode}
            placeholder="e.g. 1A2B3C"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={6}
            editable={state !== 'submitting'}
          />
          <ControlButton
            label={state === 'submitting' ? 'Pairing…' : 'Pair'}
            variant="primary"
            onPress={() => void submitPin(code)}
            disabled={state === 'submitting' || code.trim().length !== 6}
          />
        </View>
      ) : (
        <PinPad onSubmit={pin => void submitPin(pin)} disabled={state === 'submitting'} />
      )}
      {state === 'submitting' ? <Text style={styles.status}>Pairing…</Text> : null}
      {error ? <Text style={[commonStyles.errorText, styles.error]}>{error}</Text> : null}
      {sessionExpiredHint ? <Text style={styles.hint}>{sessionExpiredHint}</Text> : null}
      <View style={styles.actions}>
        {error ? (
          <ControlButton
            label="Connection error details"
            onPress={() => navigation.navigate('ConnectionError', {message: error})}
          />
        ) : null}
        <ControlButton label="Back to Discovery" onPress={() => navigation.navigate('Discovery')} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  sub: {marginTop: 12, marginBottom: 24},
  status: {color: '#A1A1B5', marginTop: 16, textAlign: 'center'},
  success: {color: '#22C55E', fontSize: 16, textAlign: 'center', marginVertical: 24},
  error: {marginTop: 16, textAlign: 'center'},
  hint: {color: '#A1A1B5', fontSize: 14, lineHeight: 20, marginTop: 12, textAlign: 'center'},
  actions: {marginTop: 24, gap: 12},
  codeBox: {width: '100%', gap: 16, alignItems: 'stretch'},
  codeInput: {
    backgroundColor: colors.surfaceElevated,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    color: colors.text,
    minHeight: 56,
    paddingHorizontal: 14,
    fontSize: 22,
    textAlign: 'center',
    letterSpacing: 4,
  },
});
