// Premium dark theme. Black/charcoal surfaces, blue accent, large touch targets.
import {StyleSheet} from 'react-native';

export const colors = {
  background: '#0A0A0F',
  surface: '#1A1A22',
  surfaceElevated: '#23232E',
  surfaceMuted: '#12121A',
  border: '#2A2A35',
  text: '#FFFFFF',
  textSecondary: '#A1A1B5',
  textMuted: '#6B6B7E',
  accent: '#2E7CF6',
  accentLight: '#3B82F6',
  accentDark: '#1D5FD6',
  success: '#22C55E',
  error: '#EF4444',
  warning: '#F59E0B',
  // Streaming brand colours (text-based branding only, no trademarked assets)
  netflix: '#E50914',
  primeVideo: '#00A8E1',
  youtube: '#FF0000',
  disney: '#113CCF',
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
};

export const sizes = {
  /** Minimum touch target height/width, per spec. */
  minTouch: 56,
  buttonRadius: 14,
  cardRadius: 16,
  dpadButton: 64,
  dpadCenter: 76,
};

export const theme = {
  colors,
  spacing,
  sizes,
};

export const commonStyles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.md,
  },
  screenCentered: {
    flex: 1,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.md,
    justifyContent: 'center',
  },
  title: {
    color: colors.text,
    fontSize: 28,
    fontWeight: '700',
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: 16,
    lineHeight: 22,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '600',
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: sizes.cardRadius,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  errorText: {
    color: colors.error,
    fontSize: 14,
    lineHeight: 20,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 22,
  },
});

export default theme;
