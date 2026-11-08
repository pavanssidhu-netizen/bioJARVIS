import 'package:flutter/material.dart';

import '../state/app_state.dart';
import '../ui/theme.dart';

class DiagnosticsPage extends StatefulWidget {
  const DiagnosticsPage(this.c, {super.key});
  final AppController c;

  @override
  State<DiagnosticsPage> createState() => _DiagnosticsPageState();
}

class _DiagnosticsPageState extends State<DiagnosticsPage> {
  bool _metadataOpen = false;
  bool _modelsOpen = false;
  bool _techOpen = false;

  String _resolveProviderLabel(Object? rawDb) {
    final s = '${rawDb ?? ''}'.toLowerCase();
    if (s.contains('turso') || s.contains('libsql')) return 'Turso';
    if (s.isNotEmpty) return 'SQLite';
    return 'Turso';
  }

  String _formatLastWrite(Object? rawIso, DateTime? fallback) {
    final dt = (rawIso is String ? DateTime.tryParse(rawIso) : null) ?? fallback;
    if (dt == null) return '—';
    final u = dt.toUtc();
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final m = months[(u.month - 1).clamp(0, 11)];
    final hh = u.hour.toString().padLeft(2, '0');
    final mm = u.minute.toString().padLeft(2, '0');
    return '${u.day} $m, $hh:$mm UTC';
  }

  String _resolveCameraSharingStatus(AppController c) {
    if (c.cameraStreamingToGemini) return 'Sharing (1 fps)';
    if (c.liveFeedActive && c.cameraOpen) return 'Perception only';
    return 'Off';
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final h = c.health ?? const {};
    final caps = c.capabilities ?? const {};
    final provider = _resolveProviderLabel(h['database']);
    final lastWrite = _formatLastWrite(h['last_db_write'], c.lastDbWriteSeen);
    final sharingLabel = _resolveCameraSharingStatus(c);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 28),
      children: [
        // Top header: exp_001 + Diagnostics + Refresh button
        Text(
          c.experimentId,
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: LM.text),
        ),
        const SizedBox(height: 6),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Diagnostics',
                    style: TextStyle(fontSize: 27, fontWeight: FontWeight.w800, color: LM.text, letterSpacing: -0.4),
                  ),
                  SizedBox(height: 2),
                  Text(
                    'Connections and capture activity',
                    style: TextStyle(fontSize: 14, color: LM.muted),
                  ),
                ],
              ),
            ),
            SizedBox(
              height: 38,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: LM.teal,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 18),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                onPressed: c.refreshDiagnostics,
                child: const Text('Refresh', style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),

        // 1. Connections Card
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: LM.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: LM.line, width: 1.2),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Connections', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: LM.text)),
              const SizedBox(height: 10),
              _StatusItemRow(
                icon: Icons.terminal_outlined,
                label: 'Backend API',
                badgeText: c.appConnected ? 'Connected' : 'Unreachable',
                state: c.appConnected ? _PillState.activeOk : _PillState.error,
              ),
              const Divider(height: 18, color: LM.line),
              _StatusItemRow(
                icon: Icons.storage_outlined,
                label: 'Database',
                badgeText: c.databaseConnected ? 'Connected' : 'Disconnected',
                state: c.databaseConnected ? _PillState.activeOk : _PillState.error,
              ),
              const Divider(height: 18, color: LM.line),
              _StatusItemRow(
                icon: Icons.person_add_alt_outlined,
                label: 'Gemini assistant',
                badgeText: c.geminiConnected
                    ? 'Connected'
                    : c.geminiConnecting
                        ? 'Connecting…'
                        : 'Not connected',
                state: c.geminiConnected
                    ? _PillState.activeOk
                    : c.geminiConnecting
                        ? _PillState.warning
                        : _PillState.inactive,
                subtitle: c.geminiConnected
                    ? 'Connected (${c.geminiModel ?? 'live'}).'
                    : 'Connect the assistant from Live Lab.',
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),

        // 2. Capture activity Card
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: LM.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: LM.line, width: 1.2),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Capture activity', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: LM.text)),
              const SizedBox(height: 10),
              _StatusItemRow(
                icon: Icons.mic_none_rounded,
                label: 'Microphone',
                badgeText: c.microphoneEnabled ? 'On' : 'Off',
                state: c.microphoneEnabled ? _PillState.activeOk : _PillState.inactive,
              ),
              const Divider(height: 18, color: LM.line),
              _StatusItemRow(
                icon: Icons.camera_alt_outlined,
                label: 'Camera',
                badgeText: c.cameraOpen ? 'On' : 'Off',
                state: c.cameraOpen ? _PillState.activeOk : _PillState.inactive,
              ),
              const Divider(height: 18, color: LM.line),
              _StatusItemRow(
                icon: Icons.smart_display_outlined,
                label: 'Camera sharing with Gemini',
                badgeText: sharingLabel,
                state: c.cameraStreamingToGemini
                    ? _PillState.activeOk
                    : (c.liveFeedActive && c.cameraOpen)
                        ? _PillState.warning
                        : _PillState.inactive,
              ),
              const Divider(height: 18, color: LM.line),
              _StatusItemRow(
                icon: Icons.videocam_outlined,
                label: 'Experiment recording',
                badgeText: c.recordingActive ? 'Recording' : 'Not recording',
                state: c.recordingActive ? _PillState.activeOk : _PillState.inactive,
              ),
              const Divider(height: 18, color: LM.line),
              _StatusItemRow(
                icon: Icons.search_rounded,
                label: 'Snapshot analysis',
                badgeText: c.snapshotAnalysisInProgress ? 'Analysing…' : 'Idle',
                state: c.snapshotAnalysisInProgress ? _PillState.warning : _PillState.inactive,
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),

        // 3. Data storage Card
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: LM.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: LM.line, width: 1.2),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Data storage', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: LM.text)),
              const SizedBox(height: 10),
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      'Database connection',
                      style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w500, color: LM.text),
                    ),
                  ),
                  _DiagnosticBadge(
                    label: c.databaseConnected ? 'Connected' : 'Disconnected',
                    state: c.databaseConnected ? _PillState.activeOk : _PillState.error,
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 16,
                runSpacing: 4,
                alignment: WrapAlignment.spaceBetween,
                children: [
                  Text('Provider: $provider', style: const TextStyle(fontSize: 13.5, color: LM.text)),
                  Text('Last write: $lastWrite', style: const TextStyle(fontSize: 13.5, color: LM.text)),
                ],
              ),
              const Divider(height: 20, color: LM.line),
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () => setState(() => _metadataOpen = !_metadataOpen),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Connection metadata',
                          style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, color: LM.text),
                        ),
                      ),
                      Icon(
                        _metadataOpen ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                        size: 20,
                        color: LM.muted,
                      ),
                    ],
                  ),
                ),
              ),
              if (_metadataOpen) ...[
                const SizedBox(height: 10),
                _kvRow('Database target', '${h['database'] ?? '—'}'),
                _kvRow('Recording session', '${c.recording?['id'] ?? 'None'}'),
                _kvRow('Recording status', '${c.recording?['status'] ?? 'inactive'}'),
                _kvRow('Last sequence #', '${c.lastSeq}'),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),

        // 4. Expandable Models and capabilities + Technical details Card
        Container(
          decoration: BoxDecoration(
            color: LM.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: LM.line, width: 1.2),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Models and capabilities
              InkWell(
                borderRadius: const BorderRadius.vertical(top: Radius.circular(14)),
                onTap: () => setState(() => _modelsOpen = !_modelsOpen),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Models and capabilities',
                          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: LM.text),
                        ),
                      ),
                      Icon(
                        _modelsOpen ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                        size: 20,
                        color: LM.muted,
                      ),
                    ],
                  ),
                ),
              ),
              if (_modelsOpen)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                  child: Column(
                    children: [
                      _kvRow('Gemini key configured', '${caps['gemini_configured'] ?? false}'),
                      _kvRow('Live voice model', '${caps['live_model'] ?? '—'}'),
                      _kvRow('Vision model', '${caps['vision_model'] ?? '—'}'),
                      _kvRow('Vision provider', '${caps['vision_provider'] ?? '—'}'),
                      _kvRow(
                        'Specialist vision council',
                        (caps['specialist_vision'] as Map?)?['configured'] == true ? 'Configured' : 'Not configured',
                      ),
                      _kvRow('Modal cloud', caps['modal_enabled'] == true ? 'Enabled' : 'Disabled'),
                      _kvRow('Registered tools', ((caps['tools'] as List?) ?? const []).join(', ')),
                      _kvRow(
                        'Steering documents',
                        ((caps['steering_docs'] as List?) ?? const []).map((d) => d['id']).join(', '),
                      ),
                    ],
                  ),
                ),
              const Divider(height: 1, color: LM.line),

              // Technical details
              InkWell(
                borderRadius: const BorderRadius.vertical(bottom: Radius.circular(14)),
                onTap: () => setState(() => _techOpen = !_techOpen),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Technical details',
                          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: LM.text),
                        ),
                      ),
                      Icon(
                        _techOpen ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                        size: 20,
                        color: LM.muted,
                      ),
                    ],
                  ),
                ),
              ),
              if (_techOpen)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                  child: Column(
                    children: [
                      _kvRow('Session ID', c.api.sessionId),
                      _kvRow('Mic permission', c.micPermission),
                      _kvRow('Camera permission', c.cameraPermission),
                      _kvRow(
                        'Camera tracks',
                        c.media.cameraTrackStates().isEmpty ? 'None active' : c.media.cameraTrackStates(),
                      ),
                      _kvRow('Frames sent to Gemini', '${c.framesSent}'),
                      _kvRow('Telemetry spans (60m)', '${c.telemetry?['spans'] ?? 0}'),
                      for (final g in ((c.telemetry?['by_name'] as List?) ?? const [])
                          .cast<Map>()
                          .where((g) => !'${g['name']}'.startsWith('api.'))
                          .take(6))
                        _kvRow('${g['name']}', 'n=${g['n']} · p50 ${g['p50_ms']}ms · p95 ${g['p95_ms']}ms'),
                      _kvRow('Last error', c.lastError ?? 'None'),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _kvRow(String key, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 150,
            child: Text(key, style: const TextStyle(fontSize: 12.5, color: LM.muted)),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: const TextStyle(fontFamily: LM.mono, fontSize: 12.5, color: LM.text),
            ),
          ),
        ],
      ),
    );
  }
}

enum _PillState { activeOk, inactive, warning, error }

class _StatusItemRow extends StatelessWidget {
  const _StatusItemRow({
    required this.icon,
    required this.label,
    required this.badgeText,
    required this.state,
    this.subtitle,
  });

  final IconData icon;
  final String label;
  final String badgeText;
  final _PillState state;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 21, color: LM.text),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                label,
                style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w500, color: LM.text),
              ),
            ),
            const SizedBox(width: 8),
            _DiagnosticBadge(label: badgeText, state: state),
          ],
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 5),
          Padding(
            padding: const EdgeInsets.only(left: 33),
            child: Text(subtitle!, style: const TextStyle(fontSize: 13.5, color: LM.muted)),
          ),
        ],
      ],
    );
  }
}

class _DiagnosticBadge extends StatelessWidget {
  const _DiagnosticBadge({required this.label, required this.state});
  final String label;
  final _PillState state;

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = switch (state) {
      _PillState.activeOk => (LM.okBg, LM.okText),
      _PillState.inactive => (LM.pillNeutralBg, LM.text),
      _PillState.warning => (LM.reviewBg, LM.reviewText),
      _PillState.error => (const Color(0xFFFEE2E2), LM.rec),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: fg),
      ),
    );
  }
}
