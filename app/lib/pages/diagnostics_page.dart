import 'package:flutter/material.dart';

import '../state/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class DiagnosticsPage extends StatelessWidget {
  const DiagnosticsPage(this.c, {super.key});
  final AppController c;

  Widget _row(String k, Object? v, {bool? good}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 170, child: Text(k, style: const TextStyle(color: LM.muted, fontSize: 12.5))),
          if (good != null) ...[
            Icon(good ? Icons.check_circle : Icons.cancel, size: 14, color: good ? LM.ok : LM.muted),
            const SizedBox(width: 6),
          ],
          Expanded(child: SelectableText('$v', style: const TextStyle(fontFamily: LM.mono, fontSize: 12.5))),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final h = c.health ?? const {};
    final caps = c.capabilities ?? const {};
    return ListView(padding: const EdgeInsets.fromLTRB(12, 0, 12, 24), children: [
      Panel(
        title: 'State (each flag independent)',
        icon: Icons.tune,
        trailing: IconButton(onPressed: c.refreshDiagnostics, icon: const Icon(Icons.refresh, color: LM.teal)),
        child: Column(children: [
          _row('app_connected', c.appConnected, good: c.appConnected),
          _row('gemini_connected', c.geminiConnected, good: c.geminiConnected),
          _row('microphone_enabled', c.microphoneEnabled, good: c.microphoneEnabled),
          _row('camera_open', c.cameraOpen, good: c.cameraOpen),
          _row('camera_streaming_to_gemini', c.cameraStreamingToGemini, good: c.cameraStreamingToGemini),
          _row('recording_active', c.recordingActive, good: c.recordingActive),
          _row('snapshot_analysis', c.snapshotAnalysisInProgress),
          _row('database_connected', c.databaseConnected, good: c.databaseConnected),
        ]),
      ),
      const SizedBox(height: 12),
      Panel(
        title: 'Backend',
        icon: Icons.dns_outlined,
        child: Column(children: [
          _row('API status', h['status'] ?? 'unreachable', good: h['status'] == 'ok'),
          _row('Database', h['database'] ?? '—'),
          _row('Last DB write', h['last_db_write'] ?? '—'),
          _row('Recording session', c.recording?['id'] ?? '—'),
          _row('Recording status', c.recording?['status'] ?? '—'),
          _row('Last seq seen', c.lastSeq),
        ]),
      ),
      const SizedBox(height: 12),
      Panel(
        title: 'Capabilities',
        icon: Icons.extension_outlined,
        child: Column(children: [
          _row('Gemini key on server', caps['gemini_configured'], good: caps['gemini_configured'] == true),
          _row('Live model', caps['live_model'] ?? '—'),
          _row('Vision model', caps['vision_model'] ?? '—'),
          _row('Vision provider', caps['vision_provider'] ?? '—'),
          _row('Specialist vision', (caps['specialist_vision'] as Map?)?['configured'] == true ? 'configured' : 'not configured'),
          _row('Modal', caps['modal_enabled'] == true ? 'enabled' : 'disabled'),
          _row('Raw media storage', caps['raw_media_storage'] == true ? 'on' : 'off'),
          _row('Tools', (caps['tools'] as List?)?.join(', ') ?? '—'),
          _row('Model routing', ((caps['routing'] as Map?) ?? const {}).entries.map((e) => '${e.key}=${e.value}').join('\n')),
          _row('Steering docs', ((caps['steering_docs'] as List?) ?? const []).map((d) => d['id']).join(', ')),
        ]),
      ),
      const SizedBox(height: 12),
      Panel(
        title: 'Telemetry (last 60 min)',
        icon: Icons.speed,
        trailing: Text('${c.telemetry?['spans'] ?? 0} spans', style: const TextStyle(fontSize: 11, color: LM.muted)),
        child: Column(children: [
          for (final g in ((c.telemetry?['by_name'] as List?) ?? const [])
              .cast<Map>()
              .where((g) => !'${g['name']}'.startsWith('api.'))
              .take(12))
            _row('${g['name']}', 'n=${g['n']}  p50 ${g['p50_ms']}ms  p95 ${g['p95_ms']}ms  err ${g['errors']}',
                good: g['errors'] == 0),
          _row('Session id', c.api.sessionId),
        ]),
      ),
      const SizedBox(height: 12),
      Panel(
        title: 'Browser',
        icon: Icons.phone_iphone,
        child: Column(children: [
          _row('Mic permission', c.micPermission),
          _row('Camera permission', c.cameraPermission),
          _row('Camera tracks (last session)', c.media.cameraTrackStates().isEmpty ? '—' : c.media.cameraTrackStates()),
          _row('Frames sent to Gemini', c.framesSent),
          _row('Last error', c.lastError ?? '—'),
        ]),
      ),
    ]);
  }
}
