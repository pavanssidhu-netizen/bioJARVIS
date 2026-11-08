import 'package:flutter/material.dart';

class LM {
  static const bg = Color(0xFF0B1215);
  static const surface = Color(0xFF111B1F);
  static const surfaceHi = Color(0xFF17252A);
  static const line = Color(0xFF223338);
  static const teal = Color(0xFF2DD4BF);
  static const tealDim = Color(0xFF0F766E);
  static const text = Color(0xFFE2ECEE);
  static const muted = Color(0xFF8AA0A6);
  static const rec = Color(0xFFEF4444);
  static const warn = Color(0xFFF59E0B);
  static const ok = Color(0xFF22C55E);
  static const mono = 'monospace';
}

ThemeData labmateTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: LM.teal,
    brightness: Brightness.dark,
    surface: LM.surface,
    primary: LM.teal,
    error: LM.rec,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: LM.bg,
    cardTheme: const CardThemeData(color: LM.surface, elevation: 0, margin: EdgeInsets.zero),
    dividerColor: LM.line,
    appBarTheme: const AppBarTheme(backgroundColor: LM.bg, elevation: 0, scrolledUnderElevation: 0),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: LM.surface,
      indicatorColor: LM.tealDim.withValues(alpha: 0.5),
      labelTextStyle: WidgetStateProperty.all(const TextStyle(fontSize: 11, color: LM.muted)),
    ),
    textTheme: const TextTheme(
      bodyMedium: TextStyle(color: LM.text, fontSize: 14),
      bodySmall: TextStyle(color: LM.muted, fontSize: 12),
      titleMedium: TextStyle(color: LM.text, fontWeight: FontWeight.w600, letterSpacing: 0.2),
    ),
  );
}
