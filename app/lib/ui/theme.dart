import 'package:flutter/material.dart';

class LM {
  // Core shared palette (matches visual references & specification)
  static const bg = Color(0xFFF4F7F6);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceHi = Color(0xFFE9F5F1);
  static const softTeal = Color(0xFFE9F5F1);
  static const line = Color(0xFFDCE6E2);
  static const teal = Color(0xFF087F73);
  static const tealDim = Color(0xFF06635A);
  static const text = Color(0xFF172F38);
  static const muted = Color(0xFF53676F);

  // Semantic statuses & accents
  static const reviewBg = Color(0xFFFFF3D6);
  static const reviewBorder = Color(0xFFD8B46C);
  static const reviewText = Color(0xFF8B4E0F);

  static const paperBg = Color(0xFFFBF8EE);
  static const paperLine = Color(0xFFE6DFC8);
  static const darkCard = Color(0xFF122B32);

  static const rec = Color(0xFFDC2626);
  static const warn = Color(0xFF8B4E0F);
  static const ok = Color(0xFF15803D);
  static const okBg = Color(0xFFD8F3DF);
  static const okText = Color(0xFF135E2E);

  static const pillNeutralBg = Color(0xFFE4EAE8);
  static const pillNeutralText = Color(0xFF475B63);

  static const mono = 'monospace';
  static const sans = 'Segoe UI';
}

ThemeData labmateTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: LM.teal,
    brightness: Brightness.light,
    surface: LM.surface,
    primary: LM.teal,
    onPrimary: Colors.white,
    secondary: LM.teal,
    onSurface: LM.text,
    error: LM.rec,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    fontFamily: LM.sans,
    fontFamilyFallback: const ['-apple-system', 'BlinkMacSystemFont', 'Inter', 'Roboto', 'sans-serif'],
    scaffoldBackgroundColor: LM.bg,
    cardTheme: const CardThemeData(
      color: LM.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
    ),
    dividerColor: LM.line,
    appBarTheme: const AppBarTheme(
      backgroundColor: LM.bg,
      foregroundColor: LM.text,
      elevation: 0,
      scrolledUnderElevation: 0,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: LM.teal,
        foregroundColor: Colors.white,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: LM.text,
        side: const BorderSide(color: LM.line, width: 1.2),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        textStyle: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: LM.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: LM.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: LM.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: LM.teal, width: 1.5),
      ),
      hintStyle: const TextStyle(color: LM.muted, fontSize: 14),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: LM.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      indicatorColor: LM.softTeal,
      iconTheme: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.selected)) {
          return const IconThemeData(color: LM.teal, size: 23);
        }
        return const IconThemeData(color: LM.muted, size: 22);
      }),
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.selected)) {
          return const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: LM.teal);
        }
        return const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w500, color: LM.muted);
      }),
    ),
    textTheme: const TextTheme(
      headlineSmall: TextStyle(color: LM.text, fontSize: 24, fontWeight: FontWeight.w800, letterSpacing: -0.3),
      titleLarge: TextStyle(color: LM.text, fontSize: 20, fontWeight: FontWeight.w700, letterSpacing: -0.2),
      titleMedium: TextStyle(color: LM.text, fontSize: 16, fontWeight: FontWeight.w700),
      bodyLarge: TextStyle(color: LM.text, fontSize: 15, height: 1.4),
      bodyMedium: TextStyle(color: LM.text, fontSize: 14, height: 1.38),
      bodySmall: TextStyle(color: LM.muted, fontSize: 12.5, height: 1.35),
    ),
  );
}
