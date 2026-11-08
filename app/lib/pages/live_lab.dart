import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/platform_web.dart' show cameraViewType;
import '../state/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class LiveLabPage extends StatelessWidget {
  const LiveLabPage(this.c, {super.key});
  final AppController c;

  @override
  Widget build(BuildContext context) {
    if (c.liveFeedActive || c.liveFeedStarting) return _LiveFeedView(c);
    return ListView(padding: const EdgeInsets.fromLTRB(12, 4, 12, 24), children: [
      _Landing(c),
      const SizedBox(height: 16),
      ProtocolPanel(c, dense: true),
      const SizedBox(height: 12),
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 4),
          title: const Text('Manual controls', style: TextStyle(fontSize: 13, color: LM.muted)),
          subtitle: const Text('Operate camera, mic, Gemini and recording individually', style: TextStyle(fontSize: 11.5, color: LM.muted)),
          children: [
            _RecordingPanel(c),
            const SizedBox(height: 12),
            _AudioPanel(c),
            const SizedBox(height: 12),
            _CameraPanel(c),
            const SizedBox(height: 12),
          ],
        ),
      ),
      Panel(
        title: 'Latest data',
        icon: Icons.stream,
        trailing: Text('${c.feed.length} items', style: Theme.of(context).textTheme.bodySmall),
        child: c.feed.isEmpty
            ? const Text('No events yet.', style: TextStyle(color: LM.muted))
            : Column(children: [for (final i in c.feed.take(5)) FeedTile(i, key: ValueKey(i.key))]),
      ),
    ]);
  }
}

class ProtocolPanel extends StatelessWidget {
  const ProtocolPanel(this.c, {super.key, this.dense = false});
  final AppController c;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final steps = c.protocolSteps;
    if (steps.isEmpty) return const SizedBox.shrink();
    final content = c.protocol!['content'] as Map;
    return Panel(
      title: 'Protocol v${c.protocol!['version']}',
      icon: Icons.checklist_rtl,
      trailing: Flexible(
        child: Text('${content['title']}',
            overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11.5, color: LM.muted)),
      ),
      child: Column(children: [
        for (final s in steps)
          _StepTile(s, selected: c.highlightedStep == s['id'], dense: dense, onTap: () => c.selectProtocolStep('${s['id']}')),
      ]),
    );
  }
}

class _StepTile extends StatelessWidget {
  const _StepTile(this.s, {required this.selected, required this.onTap, this.dense = false});
  final Map<String, dynamic> s;
  final bool selected, dense;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final qty = s['quantity'] != null ? '${s['quantity'] is num && (s['quantity'] as num) % 1 == 0 ? (s['quantity'] as num).toInt() : s['quantity']} ${s['unit'] ?? ''}' : null;
    return Semantics(
      button: true,
      selected: selected,
      label: 'Protocol step ${s['id']}',
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          margin: const EdgeInsets.only(bottom: 6),
          padding: EdgeInsets.all(dense ? 8 : 10),
          decoration: BoxDecoration(
            color: selected ? LM.teal.withValues(alpha: 0.12) : LM.surfaceHi,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: selected ? LM.teal : LM.line),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 30,
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(vertical: 2),
              decoration: BoxDecoration(
                  color: selected ? LM.teal : LM.bg, borderRadius: BorderRadius.circular(4), border: Border.all(color: LM.line)),
              child: Text('${s['id']}',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: selected ? Colors.black : LM.text)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${s['description']}', style: const TextStyle(fontSize: 13)),
                if (!dense && (qty != null || s['expected_observation'] != null))
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Text(
                        [?qty, if (s['tolerance'] != null) '(${s['tolerance']})',
                          if (s['expected_observation'] != null) '→ ${s['expected_observation']}'].join('  '),
                        style: const TextStyle(fontSize: 11.5, color: LM.muted)),
                  ),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _Landing extends StatelessWidget {
  const _Landing(this.c);
  final AppController c;

  Widget _point(IconData i, String t) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(i, size: 18, color: LM.teal),
          const SizedBox(width: 10),
          Expanded(child: Text(t, style: const TextStyle(fontSize: 13.5, height: 1.35))),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final ready = c.appConnected && (c.capabilities?['gemini_configured'] == true);
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: LM.line),
        gradient: const LinearGradient(
            begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF0F2529), LM.surface]),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Text('Hands-free lab notebook', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 6),
        const Text('Point your phone at the bench and talk.', style: TextStyle(color: LM.muted)),
        const SizedBox(height: 18),
        _point(Icons.visibility_outlined, 'Camera frames are analysed into objects, actions and action counts, and logged to the experiment database.'),
        _point(Icons.mic_none, 'Speak notes ("note that tube A turned blue") and they are saved as observations.'),
        _point(Icons.manage_search, 'Ask the log ("how many drops did I add 30 seconds ago?") and LABMATE answers from the database.'),
        _point(Icons.lock_outline, 'Nothing starts until you press the button. Stop ends camera, mic, Gemini and recording at once. Raw video/audio is never stored.'),
        const SizedBox(height: 14),
        SizedBox(
          height: 58,
          child: FilledButton.icon(
            style: FilledButton.styleFrom(textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            // startLiveFeed() unlocks audio synchronously inside this tap (iOS requirement).
            onPressed: ready ? () => c.startLiveFeed() : null,
            icon: const Icon(Icons.play_arrow_rounded, size: 30),
            label: const Text('Start live feed'),
          ),
        ),
        if (!ready)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              !c.appConnected ? 'Waiting for backend…' : 'Backend has no Gemini key configured (see Diagnostics).',
              textAlign: TextAlign.center,
              style: const TextStyle(color: LM.warn, fontSize: 12.5),
            ),
          ),
      ]),
    );
  }
}

class _LiveFeedView extends StatefulWidget {
  const _LiveFeedView(this.c);
  final AppController c;
  @override
  State<_LiveFeedView> createState() => _LiveFeedViewState();
}

class _LiveFeedViewState extends State<_LiveFeedView> {
  final _ask = TextEditingController();
  bool _asking = false;
  Map<String, dynamic>? _answer;

  @override
  void dispose() {
    _ask.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final q = _ask.text.trim();
    if (q.isEmpty) return;
    setState(() => _asking = true);
    final r = await widget.c.askLog(q);
    if (mounted) {
      setState(() {
        _asking = false;
        _answer = r;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final p = c.latestPerception;
    final actions = (p?['actions'] as List?) ?? const [];
    final objects = (p?['objects'] as List?) ?? const [];
    return ListView(padding: const EdgeInsets.fromLTRB(12, 4, 12, 24), children: [
      // ---- camera with perception overlay ----
      ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: AspectRatio(
          aspectRatio: 3 / 4,
          child: Stack(fit: StackFit.expand, children: [
            if (c.cameraOpen) const HtmlElementView(viewType: cameraViewType) else Container(color: Colors.black),
            if (c.liveFeedStarting)
              const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
                CircularProgressIndicator(),
                SizedBox(height: 10),
                Text('Starting camera, recording and Gemini…'),
              ])),
            Positioned(
              left: 10,
              top: 10,
              child: Wrap(spacing: 6, children: [
                if (c.recordingActive) const StatusPill(label: 'REC', on: true, onColor: LM.rec, pulse: true),
                StatusPill(label: c.geminiConnected ? 'Voice' : 'Voice off', on: c.geminiConnected && c.microphoneEnabled,
                    icon: c.microphoneEnabled ? Icons.mic : Icons.mic_off),
                StatusPill(label: 'Perception ${c.perceptionSaved}/${c.perceptionWindows}', on: c.perceptionWindows > 0, icon: Icons.visibility),
              ]),
            ),
            if (p != null)
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                child: Container(
                  padding: const EdgeInsets.fromLTRB(12, 24, 12, 12),
                  decoration: const BoxDecoration(
                      gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Colors.transparent, Color(0xE6000000)])),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Row(children: [
                      Expanded(child: Text('${p['scene_summary']}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
                      PersistenceBadge(c.latestPerceptionSaved ? Persistence.saved : Persistence.notSaved),
                    ]),
                    const SizedBox(height: 6),
                    Wrap(spacing: 6, runSpacing: 6, children: [
                      for (final a in actions)
                        _chip('${a['action']}${a['object'] != null ? ' · ${a['object']}' : ''}  ×${a['count']}', LM.warn, '${a['certainty']}'),
                      for (final o in objects.take(6))
                        _chip('${o['label']}${o['count'] != null ? ' ×${o['count']}' : ''}', LM.teal, '${o['certainty']}'),
                    ]),
                  ]),
                ),
              ),
          ]),
        ),
      ),
      const SizedBox(height: 10),
      SizedBox(
        height: 52,
        child: FilledButton.icon(
          style: FilledButton.styleFrom(backgroundColor: LM.rec, textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          onPressed: () => c.stopLiveFeed(),
          icon: const Icon(Icons.stop_rounded),
          label: const Text('Stop live feed'),
        ),
      ),
      const SizedBox(height: 12),
      ProtocolPanel(c),
      const SizedBox(height: 12),
      // ---- ask the log (typed fallback for the voice query) ----
      Panel(
        title: 'Ask the log',
        icon: Icons.manage_search,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('Say it out loud, or type: "How many drops did I add in the last 30 seconds?"',
              style: TextStyle(color: LM.muted, fontSize: 12.5)),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(
              child: TextField(
                controller: _ask,
                decoration: const InputDecoration(isDense: true, border: OutlineInputBorder(), hintText: 'Question about this experiment'),
                onSubmitted: (_) => _submit(),
              ),
            ),
            IconButton(
              onPressed: _asking ? null : _submit,
              icon: _asking
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.send, color: LM.teal),
            ),
          ]),
          if (_answer != null) ...[
            const SizedBox(height: 8),
            Text('${_answer!['answer']}', style: const TextStyle(fontWeight: FontWeight.w600)),
            Text('confidence: ${_answer!['confidence']} · ${(_answer!['evidence_event_ids'] as List).length} events cited · '
                '${_answer!['events_considered']} considered', style: Theme.of(context).textTheme.bodySmall),
          ],
        ]),
      ),
      const SizedBox(height: 12),
      _AudioPanel(c),
      const SizedBox(height: 12),
      Panel(
        title: 'Live data stream',
        icon: Icons.stream,
        trailing: Text('seq #${c.lastSeq}', style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.muted)),
        child: c.feed.isEmpty
            ? const Text('Waiting for first events…', style: TextStyle(color: LM.muted))
            : Column(children: [for (final i in c.feed.take(8)) FeedTile(i, key: ValueKey(i.key))]),
      ),
    ]);
  }

  Widget _chip(String label, Color color, String certainty) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: color.withValues(alpha: certainty == 'uncertain' ? 0.12 : 0.25),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: certainty == 'certain' ? 0.9 : 0.5)),
        ),
        child: Text(label, style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
      );
}

class StatusHeader extends StatelessWidget implements PreferredSizeWidget {
  const StatusHeader(this.c, {super.key});
  final AppController c;
  @override
  Size get preferredSize => const Size.fromHeight(92);

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 8, 14, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(
              width: 26,
              height: 26,
              decoration: BoxDecoration(borderRadius: BorderRadius.circular(7), border: Border.all(color: LM.teal, width: 1.5)),
              child: const Icon(Icons.biotech, size: 16, color: LM.teal),
            ),
            const SizedBox(width: 10),
            const Text('LABMATE', style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: 3, fontSize: 16)),
            const Spacer(),
            Text(c.experimentId, style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.muted)),
          ]),
          const SizedBox(height: 10),
          Wrap(spacing: 6, runSpacing: 6, children: [
            StatusPill(label: 'Backend', on: c.appConnected, onColor: LM.ok),
            StatusPill(label: c.geminiConnecting ? 'Gemini…' : 'Gemini', on: c.geminiConnected, pulse: c.geminiConnecting),
            StatusPill(label: 'Mic', on: c.microphoneEnabled, icon: c.microphoneEnabled ? Icons.mic : Icons.mic_off),
            StatusPill(label: 'Camera', on: c.cameraOpen, icon: c.cameraOpen ? Icons.videocam : Icons.videocam_off),
            if (c.cameraStreamingToGemini) const StatusPill(label: 'Gemini sees camera', on: true, onColor: LM.warn, pulse: true),
            StatusPill(label: c.recordingActive ? 'RECORDING' : 'Not recording', on: c.recordingActive, onColor: LM.rec, pulse: true),
          ]),
        ]),
      ),
    );
  }
}

class _RecordingPanel extends StatelessWidget {
  const _RecordingPanel(this.c);
  final AppController c;
  @override
  Widget build(BuildContext context) {
    final r = c.recording;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      decoration: BoxDecoration(
        color: c.recordingActive ? LM.rec.withValues(alpha: 0.10) : LM.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: c.recordingActive ? LM.rec : LM.line, width: c.recordingActive ? 1.5 : 1),
      ),
      padding: const EdgeInsets.all(14),
      child: Row(children: [
        Icon(c.recordingActive ? Icons.fiber_manual_record : Icons.pause_circle_outline,
            color: c.recordingActive ? LM.rec : LM.muted, size: 28),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(c.recordingActive ? 'Recording experiment data' : 'Recording paused',
                style: TextStyle(fontWeight: FontWeight.w700, color: c.recordingActive ? LM.rec : LM.text)),
            const SizedBox(height: 2),
            Text(
              c.recordingActive
                  ? 'Session ${r?['id']} · ${r?['event_count'] ?? 0} events · server-enforced'
                  : 'Conversation is NOT saved. Press Start to persist observations.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ]),
        ),
        const SizedBox(width: 8),
        c.recordingActive
            ? FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: LM.rec),
                onPressed: () => c.stopRecording(),
                icon: const Icon(Icons.stop),
                label: const Text('Stop'))
            : FilledButton.icon(
                onPressed: c.appConnected ? () => c.startRecording() : null,
                icon: const Icon(Icons.fiber_manual_record),
                label: const Text('Start Recording')),
      ]),
    );
  }
}

class _AudioPanel extends StatefulWidget {
  const _AudioPanel(this.c);
  final AppController c;
  @override
  State<_AudioPanel> createState() => _AudioPanelState();
}

class _AudioPanelState extends State<_AudioPanel> {
  final _text = TextEditingController();
  final _scroll = ScrollController();

  @override
  void dispose() {
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
    return Panel(
      title: 'Conversation',
      icon: Icons.record_voice_over_outlined,
      trailing: c.geminiModel != null ? Text(c.geminiModel!, style: const TextStyle(fontFamily: LM.mono, fontSize: 10.5, color: LM.muted)) : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (!c.geminiConnected)
            FilledButton.icon(
              // connectGemini() unlocks audio output synchronously inside this tap (required on iOS).
              onPressed: c.geminiConnecting || !c.appConnected ? null : () => c.connectGemini(),
              icon: const Icon(Icons.power_settings_new),
              label: Text(c.geminiConnecting ? 'Connecting…' : 'Connect to Gemini'),
            )
          else
            OutlinedButton.icon(onPressed: () => c.disconnectGemini(), icon: const Icon(Icons.power_off), label: const Text('Disconnect')),
          c.microphoneEnabled
              ? FilledButton.icon(
                  style: FilledButton.styleFrom(backgroundColor: LM.tealDim),
                  onPressed: c.disableMic,
                  icon: const Icon(Icons.mic),
                  label: const Text('Mic on — tap to mute'))
              : OutlinedButton.icon(
                  onPressed: c.geminiConnected ? () => c.enableMic() : null,
                  icon: const Icon(Icons.mic_off),
                  label: const Text('Enable microphone')),
        ]),
        if (c.microphoneEnabled) ...[
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: (c.micLevel * 6).clamp(0, 1), minHeight: 4, backgroundColor: LM.surfaceHi),
          ),
        ],
        const SizedBox(height: 12),
        Container(
          height: 190,
          decoration: BoxDecoration(color: LM.bg, borderRadius: BorderRadius.circular(10), border: Border.all(color: LM.line)),
          child: c.transcript.isEmpty
              ? const Center(
                  child: Text('Live transcript appears here.\nTry: "What can you see?"',
                      textAlign: TextAlign.center, style: TextStyle(color: LM.muted)))
              : ListView.builder(
                  controller: _scroll,
                  padding: const EdgeInsets.all(10),
                  itemCount: c.transcript.length,
                  itemBuilder: (_, i) => _TranscriptRow(c.transcript[i]),
                ),
        ),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(
            child: TextField(
              controller: _text,
              enabled: c.geminiConnected,
              decoration: const InputDecoration(isDense: true, hintText: 'Type to Gemini…', border: OutlineInputBorder()),
              onSubmitted: (v) {
                c.sendTypedMessage(v);
                _text.clear();
              },
            ),
          ),
          IconButton(
            tooltip: 'Send',
            onPressed: c.geminiConnected
                ? () {
                    c.sendTypedMessage(_text.text);
                    _text.clear();
                  }
                : null,
            icon: const Icon(Icons.send, color: LM.teal),
          ),
        ]),
      ]),
    );
  }
}

class _TranscriptRow extends StatelessWidget {
  const _TranscriptRow(this.l);
  final TranscriptLine l;
  @override
  Widget build(BuildContext context) {
    final me = l.speaker == 'researcher';
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(
          width: 62,
          child: Text(me ? 'YOU' : 'LABMATE',
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: me ? LM.text : LM.teal, letterSpacing: 1)),
        ),
        Expanded(child: Text(l.text, style: TextStyle(color: l.final_ ? LM.text : LM.muted))),
        if (me && l.final_)
          Padding(
            padding: const EdgeInsets.only(left: 6),
            child: Icon(l.saved == true ? Icons.cloud_done : Icons.cloud_off, size: 14, color: l.saved == true ? LM.ok : LM.muted),
          ),
      ]),
    );
  }
}

class _CameraPanel extends StatelessWidget {
  const _CameraPanel(this.c);
  final AppController c;

  @override
  Widget build(BuildContext context) {
    return Panel(
      title: 'Camera & vision',
      icon: Icons.camera_alt_outlined,
      trailing: c.cameraOpen && c.multipleCameras
          ? IconButton(tooltip: 'Switch camera', icon: const Icon(Icons.cameraswitch, color: LM.teal), onPressed: c.flipCamera)
          : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (c.cameraOpen)
          ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: AspectRatio(
              aspectRatio: 4 / 3,
              child: Stack(fit: StackFit.expand, children: [
                const HtmlElementView(viewType: cameraViewType),
                if (c.cameraStreamingToGemini)
                  Positioned(
                    left: 8,
                    top: 8,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(color: LM.warn, borderRadius: BorderRadius.circular(4)),
                      child: Text('GEMINI WATCHING · ${c.framesSent} frames',
                          style: const TextStyle(color: Colors.black, fontSize: 10.5, fontWeight: FontWeight.w800)),
                    ),
                  ),
              ]),
            ),
          )
        else
          Container(
            height: 90,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: LM.bg, borderRadius: BorderRadius.circular(10), border: Border.all(color: LM.line)),
            child: const Text('Camera is off', style: TextStyle(color: LM.muted)),
          ),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          c.cameraOpen
              ? OutlinedButton.icon(onPressed: c.closeCamera, icon: const Icon(Icons.videocam_off), label: const Text('Close Camera'))
              : FilledButton.icon(onPressed: () => c.openCamera(), icon: const Icon(Icons.videocam), label: const Text('Open Camera')),
          OutlinedButton.icon(
              onPressed: c.cameraOpen ? () => c.captureSnapshot() : null,
              icon: const Icon(Icons.camera),
              label: const Text('Capture Snapshot')),
          OutlinedButton.icon(onPressed: c.uploadImage, icon: const Icon(Icons.upload_file), label: const Text('Upload')),
        ]),
        const SizedBox(height: 4),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          dense: true,
          value: c.cameraStreamingToGemini,
          onChanged: c.cameraOpen && c.geminiConnected ? c.setCameraStreaming : null,
          title: const Text('Allow Gemini to see camera frames'),
          subtitle: const Text('1 frame every 2 s while on. Frames are never stored.'),
        ),
        if (c.snapshots.isNotEmpty) ...[
          const Divider(height: 20),
          for (final s in c.snapshots.take(4)) _SnapshotCard(c, s, key: ValueKey(s.id)),
        ],
      ]),
    );
  }
}

class _SnapshotCard extends StatefulWidget {
  const _SnapshotCard(this.c, this.s, {super.key});
  final AppController c;
  final Snapshot s;
  @override
  State<_SnapshotCard> createState() => _SnapshotCardState();
}

class _SnapshotCardState extends State<_SnapshotCard> {
  late final _q = TextEditingController(text: 'What laboratory equipment and objects can you see? What is uncertain?');
  late final _bytes = base64Decode(widget.s.b64);

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c, s = widget.s, r = s.result;
    final busy = c.snapshotAnalysisInProgress;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          ClipRRect(borderRadius: BorderRadius.circular(8), child: Image.memory(_bytes, width: 92, height: 70, fit: BoxFit.cover)),
          const SizedBox(width: 10),
          Expanded(
            child: TextField(
              controller: _q,
              minLines: 2,
              maxLines: 3,
              style: const TextStyle(fontSize: 13),
              decoration: InputDecoration(
                  isDense: true, border: const OutlineInputBorder(), labelText: '${s.source} ${hhmmss(s.time)} · question'),
            ),
          ),
        ]),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 6, children: [
          FilledButton.tonalIcon(
              onPressed: busy ? null : () => c.analyseSnapshot(s, _q.text, save: false),
              icon: busy ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.auto_awesome),
              label: const Text('Analyse')),
          FilledButton.icon(
              onPressed: busy || !c.recordingActive ? null : () => c.analyseSnapshot(s, _q.text, save: true),
              icon: const Icon(Icons.save_alt),
              label: Text(c.recordingActive ? 'Analyse & Save' : 'Save needs recording')),
        ]),
        if (s.error != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(s.error!, style: const TextStyle(color: LM.rec))),
        if (r != null) ...[
          const SizedBox(height: 8),
          Row(children: [
            Text('${r['model']}', style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.muted)),
            const Spacer(),
            PersistenceBadge(r['saved'] == true ? Persistence.saved : Persistence.notSaved),
          ]),
          const SizedBox(height: 4),
          Text('${r['description']}'),
          const SizedBox(height: 6),
          JsonView(r['structured']),
        ],
      ]),
    );
  }
}
