import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/platform_web.dart' show cameraViewType;
import '../state/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class StatusHeader extends StatelessWidget implements PreferredSizeWidget {
  const StatusHeader(this.c, {super.key});
  final AppController c;

  @override
  Size get preferredSize => const Size.fromHeight(54);

  @override
  Widget build(BuildContext context) {
    final isLive = c.recordingActive || c.liveFeedActive;
    final isConnected = c.geminiConnected || c.cameraOpen;
    final badgeText = isLive
        ? 'Live session'
        : isConnected
            ? 'Live ready'
            : 'Demo session';
    final dotColor = isLive
        ? LM.rec
        : isConnected
            ? LM.ok
            : const Color(0xFF5A6D74);

    return SafeArea(
      bottom: false,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
            child: Row(
              children: [
                const Text(
                  'LARVIS',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    letterSpacing: 2.2,
                    fontSize: 22,
                    color: LM.text,
                  ),
                ),
                const Spacer(),
                InkWell(
                  borderRadius: BorderRadius.circular(20),
                  onTap: () => c.switchToTab(3),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 5),
                    decoration: BoxDecoration(
                      color: const Color(0xFFE3EAE8),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Container(
                          width: 7,
                          height: 7,
                          decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          badgeText,
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF475B63),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class LiveLabPage extends StatefulWidget {
  const LiveLabPage(this.c, {super.key});
  final AppController c;

  @override
  State<LiveLabPage> createState() => _LiveLabPageState();
}

class _LiveLabPageState extends State<LiveLabPage> {
  String _selectedChannel = 'CH08';
  List<String> _trackingLabels = ['Bubbles'];
  List<Map<String, dynamic>> _pendingReviews = [];
  bool _assistantExpanded = false;
  bool _extraCameraControlsOpen = false;
  final _utteranceCtl = TextEditingController();
  final _askCtl = TextEditingController();
  bool _askingLog = false;
  Map<String, dynamic>? _logAnswer;

  static const _channels = [
    'CH01', 'CH02', 'CH03', 'CH04', 'CH05', 'CH06',
    'CH07', 'CH08', 'CH09', 'CH10', 'CH11', 'CH12',
  ];

  @override
  void initState() {
    super.initState();
    _syncSessionAndReviews();
  }

  @override
  void dispose() {
    _utteranceCtl.dispose();
    _askCtl.dispose();
    super.dispose();
  }

  Future<void> _syncSessionAndReviews() async {
    final c = widget.c;
    _selectedChannel = c.activeChannelIdResolved;
    try {
      final revs = await c.fetchPendingReviews();
      if (mounted) setState(() => _pendingReviews = revs);
    } catch (_) {}
    if (c.recordingId != null) {
      try {
        final st = await c.fetchLiveRecordingState(c.recordingId!);
        if (!mounted) return;
        setState(() {
          if (st['active_channel_id'] is String && (st['active_channel_id'] as String).isNotEmpty) {
            _selectedChannel = st['active_channel_id'] as String;
          }
          final tr = ((st['tracking'] as List?) ?? const [])
              .map((e) => '${(e as Map)['label'] ?? ''}')
              .where((s) => s.isNotEmpty)
              .toList();
          if (tr.isNotEmpty) _trackingLabels = tr;
        });
      } catch (_) {}
    }
  }

  (String, String) _resolveStepDisplay(AppController c) {
    final steps = c.protocolSteps;
    final activeId = c.activeStepIdResolved;
    if (steps.isEmpty) {
      return ('Step 5 of 9', 'Load samples and standards');
    }
    var idx = steps.indexWhere((s) => '${s['id']}' == activeId);
    if (idx < 0) idx = steps.length >= 5 ? 4 : 0;
    final step = steps[idx];
    final total = steps.length;
    final rawAction = '${step['action'] ?? step['description'] ?? 'Load samples and standards'}';
    final cleanTitle = rawAction.toLowerCase().contains('sample') && rawAction.toLowerCase().contains('incubation')
        ? 'Load samples and standards'
        : rawAction;
    return ('Step ${idx + 1} of $total', cleanTitle);
  }

  Future<void> _selectChannel(String ch) async {
    setState(() => _selectedChannel = ch);
    final recId = widget.c.recordingId;
    if (recId != null) {
      try {
        await widget.c.updateLiveRecordingState(recId, activeChannelId: ch);
      } catch (_) {}
    }
  }

  Future<void> _showTrackingSheet() async {
    final ctl = TextEditingController();
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: LM.surface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(18))),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setModalState) {
            return Padding(
              padding: EdgeInsets.fromLTRB(16, 14, 16, MediaQuery.of(ctx).viewInsets.bottom + 20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('Tracked perception targets', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: LM.text)),
                  const SizedBox(height: 4),
                  const Text('Objects tracked by Gemini & the specialist perception council.',
                      style: TextStyle(fontSize: 12.5, color: LM.muted)),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final label in _trackingLabels)
                        InputChip(
                          label: Text(label),
                          backgroundColor: LM.softTeal,
                          onDeleted: () async {
                            setState(() => _trackingLabels.remove(label));
                            setModalState(() {});
                            if (widget.c.recordingId != null) {
                              try {
                                await widget.c.removeTrackedObject(widget.c.recordingId!, label.toLowerCase());
                              } catch (_) {}
                            }
                          },
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: ctl,
                          decoration: const InputDecoration(hintText: 'Add target (e.g. Bubbles, Meniscus, Pipette)'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      FilledButton(
                        onPressed: () async {
                          final v = ctl.text.trim();
                          if (v.isEmpty) return;
                          ctl.clear();
                          if (!_trackingLabels.contains(v)) {
                            setState(() => _trackingLabels.add(v));
                            setModalState(() {});
                          }
                          if (widget.c.recordingId != null) {
                            try {
                              await widget.c.addTrackedObject(widget.c.recordingId!, v.toLowerCase(), channelId: _selectedChannel);
                            } catch (_) {}
                          }
                        },
                        child: const Text('Track'),
                      ),
                    ],
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  Future<void> _submitLogQuestion() async {
    final q = _askCtl.text.trim();
    if (q.isEmpty) return;
    setState(() => _askingLog = true);
    final res = await widget.c.askLog(q);
    if (mounted) {
      setState(() {
        _askingLog = false;
        _logAnswer = res;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final (stepPosition, stepTitle) = _resolveStepDisplay(c);
    final p = c.effectivePerceptionPayload;
    final rawSummary = '${p['scene_summary'] ?? 'Chip and pipette in view.'}'.trim();
    final sceneSummary = rawSummary.endsWith('.') ? rawSummary : '$rawSummary.';
    final isFeedRunning = c.liveFeedActive || c.liveFeedStarting;

    // Latest assistant line if available
    String assistantPreview = 'Assistant latest-message';
    for (final line in c.transcript.reversed) {
      if (line.speaker != 'researcher' && line.text.trim().isNotEmpty) {
        assistantPreview = line.text.trim();
        break;
      }
    }

    final pendingCount = _pendingReviews.length;
    final latestPending = _pendingReviews.isNotEmpty ? _pendingReviews.first : null;
    final reviewSub = latestPending != null
        ? 'Observation awaiting your decision'
        : 'Observation awaiting your decision';

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 28),
      children: [
        // 1. Experiment context
        const Text(
          'Experiment context',
          style: TextStyle(fontSize: 13, color: LM.muted, fontWeight: FontWeight.w500),
        ),
        const SizedBox(height: 2),
        Text(
          c.experimentDisplayTitle,
          style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: LM.text, letterSpacing: -0.3),
        ),
        const SizedBox(height: 12),

        // 2. Current protocol step & All steps action
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            color: LM.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: LM.teal, width: 1.3),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      stepPosition,
                      style: const TextStyle(fontSize: 13, color: LM.muted, fontWeight: FontWeight.w500),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      stepTitle,
                      style: const TextStyle(fontSize: 16.5, fontWeight: FontWeight.w700, color: LM.text),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () => showProtocolStepsSheet(context, c),
                child: const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                  child: Text(
                    'All steps',
                    style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600, color: LM.text),
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),

        // 3. Session context bar (Channel selector & Tracking chips)
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: LM.softTeal,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'Session context',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, color: LM.text),
                ),
              ),
              PopupMenuButton<String>(
                tooltip: 'Select microfluidic channel',
                onSelected: _selectChannel,
                itemBuilder: (_) => [
                  for (final ch in _channels)
                    PopupMenuItem(
                      value: ch,
                      child: Text(ch, style: TextStyle(fontWeight: ch == _selectedChannel ? FontWeight.w700 : FontWeight.w500)),
                    ),
                ],
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: LM.surface,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: LM.teal, width: 1.1),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        _selectedChannel,
                        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: LM.teal),
                      ),
                      const SizedBox(width: 2),
                      const Icon(Icons.arrow_drop_down, size: 18, color: LM.teal),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 8),
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: _showTrackingSheet,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
                  decoration: BoxDecoration(
                    color: LM.surface,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: LM.text.withValues(alpha: 0.45), width: 1.1),
                  ),
                  child: Text(
                    _trackingLabels.isEmpty ? 'Track +' : _trackingLabels.first,
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: LM.text),
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),

        // 4. Scene summary + Large Camera/Evidence Viewer + Primary Controls
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: LM.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: LM.teal, width: 1.3),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      'Scene summary',
                      style: TextStyle(fontSize: 13, color: LM.muted, fontWeight: FontWeight.w500),
                    ),
                  ),
                  if (c.recordingActive)
                    const Padding(
                      padding: EdgeInsets.only(right: 6),
                      child: StatusPill(label: 'REC', on: true, onColor: LM.rec, pulse: true),
                    ),
                  InkWell(
                    borderRadius: BorderRadius.circular(6),
                    onTap: () => setState(() => _extraCameraControlsOpen = !_extraCameraControlsOpen),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                      child: Icon(
                        _extraCameraControlsOpen ? Icons.expand_less : Icons.tune_rounded,
                        size: 16,
                        color: LM.muted,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 2),
              Text(
                sceneSummary,
                style: const TextStyle(fontSize: 16.5, fontWeight: FontWeight.w700, color: LM.text),
              ),
              const SizedBox(height: 12),

              // Camera / Evidence Viewer
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: AspectRatio(
                  aspectRatio: 16 / 10,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      if (c.cameraOpen) ...[
                        const HtmlElementView(viewType: cameraViewType),
                        CameraBoundingBoxOverlay(perception: p),
                      ] else if (c.snapshots.isNotEmpty) ...[
                        Image.memory(base64Decode(c.snapshots.first.b64), fit: BoxFit.cover),
                        CameraBoundingBoxOverlay(perception: p),
                      ] else
                        MicrofluidicEvidenceCanvas(perception: p),
                      if (c.liveFeedStarting)
                        Container(
                          color: Colors.black54,
                          alignment: Alignment.center,
                          child: const Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              CircularProgressIndicator(color: Colors.white),
                              SizedBox(height: 10),
                              Text('Starting camera, recording & Gemini…', style: TextStyle(color: Colors.white, fontSize: 13)),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),

              // Primary Control Bar: Mic | Start/Stop Live Feed | Camera
              Row(
                children: [
                  SizedBox(
                    width: 48,
                    height: 46,
                    child: OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        padding: EdgeInsets.zero,
                        backgroundColor: c.microphoneEnabled ? LM.softTeal : LM.surface,
                        side: BorderSide(
                          color: c.microphoneEnabled ? LM.teal : const Color(0xFF6E8087),
                          width: 1.2,
                        ),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      onPressed: () async {
                        if (c.microphoneEnabled) {
                          c.disableMic();
                        } else {
                          if (!c.geminiConnected && !c.geminiConnecting) {
                            await c.connectGemini();
                          }
                          await c.enableMic();
                        }
                      },
                      child: Icon(
                        c.microphoneEnabled ? Icons.mic_rounded : Icons.mic_none_rounded,
                        color: c.microphoneEnabled ? LM.teal : LM.text,
                        size: 22,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: SizedBox(
                      height: 46,
                      child: FilledButton(
                        style: FilledButton.styleFrom(
                          backgroundColor: isFeedRunning ? LM.rec : LM.teal,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        ),
                        onPressed: () async {
                          if (isFeedRunning) {
                            await c.stopLiveFeed();
                          } else {
                            await c.startLiveFeed();
                          }
                          await _syncSessionAndReviews();
                        },
                        child: Text(
                          isFeedRunning ? 'Stop live feed' : 'Start live feed',
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  SizedBox(
                    width: 48,
                    height: 46,
                    child: OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        padding: EdgeInsets.zero,
                        backgroundColor: c.cameraOpen ? LM.softTeal : LM.surface,
                        side: BorderSide(
                          color: c.cameraOpen ? LM.teal : const Color(0xFF6E8087),
                          width: 1.2,
                        ),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                      onPressed: () async {
                        if (c.cameraOpen) {
                          c.closeCamera();
                        } else {
                          await c.openCamera();
                        }
                      },
                      onLongPress: () => setState(() => _extraCameraControlsOpen = !_extraCameraControlsOpen),
                      child: Icon(
                        c.cameraOpen ? Icons.videocam_rounded : Icons.videocam_outlined,
                        color: c.cameraOpen ? LM.teal : LM.text,
                        size: 22,
                      ),
                    ),
                  ),
                ],
              ),

              if (_extraCameraControlsOpen) ...[
                const Divider(height: 16),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    OutlinedButton.icon(
                      onPressed: c.cameraOpen ? () => c.captureSnapshot() : null,
                      icon: const Icon(Icons.camera_alt_outlined, size: 16),
                      label: const Text('Capture snapshot'),
                    ),
                    OutlinedButton.icon(
                      onPressed: c.uploadImage,
                      icon: const Icon(Icons.upload_file_outlined, size: 16),
                      label: const Text('Upload image'),
                    ),
                    OutlinedButton.icon(
                      onPressed: c.recordingActive ? () => c.stopRecording() : () => c.startRecording(),
                      icon: Icon(c.recordingActive ? Icons.stop_circle_outlined : Icons.fiber_manual_record, size: 16, color: LM.rec),
                      label: Text(c.recordingActive ? 'Stop recording' : 'Start recording'),
                    ),
                    if (c.cameraOpen && c.multipleCameras)
                      OutlinedButton.icon(
                        onPressed: c.flipCamera,
                        icon: const Icon(Icons.cameraswitch_outlined, size: 16),
                        label: const Text('Flip camera'),
                      ),
                  ],
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  value: c.cameraStreamingToGemini,
                  onChanged: c.cameraOpen && c.geminiConnected ? c.setCameraStreaming : null,
                  title: const Text('Share live frames with Gemini (1 fps)', style: TextStyle(fontSize: 13)),
                  subtitle: const Text('Session frames are purged automatically when recording ends.', style: TextStyle(fontSize: 11.5)),
                ),
                if (c.snapshots.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  for (final s in c.snapshots.take(2)) _SnapshotCompactTile(c: c, s: s),
                ],
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),

        // 5. Needs review entry point card
        InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () async {
            await showReviewObservationSheet(
              context,
              c,
              targetObservationId: latestPending?['observation_id'] as String?,
              initialSummary: latestPending?['spoken_response'] as String?,
              initialChannel: _selectedChannel,
            );
            await _syncSessionAndReviews();
          },
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            decoration: BoxDecoration(
              color: LM.reviewBg,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: LM.reviewBorder, width: 1.3),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        pendingCount > 0 ? 'Needs review' : 'Needs review',
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: LM.reviewText),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        reviewSub,
                        style: const TextStyle(fontSize: 14, color: LM.reviewText),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                const Text(
                  'Review',
                  style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700, color: LM.reviewText),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),

        // 6. Expandable Assistant latest-message bar
        Container(
          decoration: BoxDecoration(
            color: LM.darkCard,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              InkWell(
                borderRadius: BorderRadius.circular(14),
                onTap: () => setState(() => _assistantExpanded = !_assistantExpanded),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          assistantPreview,
                          maxLines: _assistantExpanded ? 3 : 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 15.5,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Icon(
                        _assistantExpanded ? Icons.keyboard_arrow_down_rounded : Icons.north_east_rounded,
                        color: Colors.white,
                        size: 20,
                      ),
                    ],
                  ),
                ),
              ),
              if (_assistantExpanded)
                Container(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Divider(color: Color(0xFF28464F), height: 16),
                      Row(
                        children: [
                          const Text(
                            'Voice & Utterance Router',
                            style: TextStyle(color: Color(0xFF9BC2C9), fontSize: 12.5, fontWeight: FontWeight.w600),
                          ),
                          const Spacer(),
                          TextButton.icon(
                            style: TextButton.styleFrom(foregroundColor: const Color(0xFF5EEAD4)),
                            onPressed: c.geminiConnected ? c.disconnectGemini : c.connectGemini,
                            icon: Icon(c.geminiConnected ? Icons.power_off : Icons.power_settings_new, size: 15),
                            label: Text(
                              c.geminiConnected ? 'Disconnect voice' : 'Connect voice',
                              style: const TextStyle(fontSize: 12),
                            ),
                          ),
                        ],
                      ),
                      Container(
                        constraints: const BoxConstraints(maxHeight: 150),
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: const Color(0xFF0B1C21),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: c.transcript.isEmpty
                            ? const Text(
                                'Speak or enter an observation below (e.g. "One bubble in channel 8" or "I am on step 5").',
                                style: TextStyle(color: Color(0xFF8AA0A6), fontSize: 12.5),
                              )
                            : ListView.builder(
                                shrinkWrap: true,
                                itemCount: c.transcript.length,
                                itemBuilder: (_, i) {
                                  final l = c.transcript[i];
                                  final me = l.speaker == 'researcher';
                                  return Padding(
                                    padding: const EdgeInsets.only(bottom: 6),
                                    child: Text(
                                      '${me ? "YOU" : "LARVIS"}: ${l.text}',
                                      style: TextStyle(
                                        color: me ? Colors.white : const Color(0xFF5EEAD4),
                                        fontSize: 12.5,
                                      ),
                                    ),
                                  );
                                },
                              ),
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _utteranceCtl,
                              style: const TextStyle(color: LM.text, fontSize: 13.5),
                              decoration: const InputDecoration(
                                isDense: true,
                                hintText: 'Record observation or command…',
                              ),
                              onSubmitted: (v) {
                                if (v.trim().isEmpty) return;
                                c.sendTypedMessage(v);
                                _utteranceCtl.clear();
                              },
                            ),
                          ),
                          const SizedBox(width: 8),
                          FilledButton(
                            onPressed: () {
                              if (_utteranceCtl.text.trim().isEmpty) return;
                              c.sendTypedMessage(_utteranceCtl.text);
                              _utteranceCtl.clear();
                            },
                            child: const Text('Send'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _askCtl,
                              style: const TextStyle(color: LM.text, fontSize: 13.5),
                              decoration: const InputDecoration(
                                isDense: true,
                                hintText: 'Ask the log (e.g. "How many bubbles were seen?")',
                              ),
                              onSubmitted: (_) => _submitLogQuestion(),
                            ),
                          ),
                          const SizedBox(width: 8),
                          FilledButton.tonal(
                            onPressed: _askingLog ? null : _submitLogQuestion,
                            child: _askingLog
                                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                                : const Text('Ask log'),
                          ),
                        ],
                      ),
                      if (_logAnswer != null) ...[
                        const SizedBox(height: 8),
                        Text(
                          '${_logAnswer!['answer']}',
                          style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600),
                        ),
                      ],
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _SnapshotCompactTile extends StatefulWidget {
  const _SnapshotCompactTile({required this.c, required this.s});
  final AppController c;
  final Snapshot s;

  @override
  State<_SnapshotCompactTile> createState() => _SnapshotCompactTileState();
}

class _SnapshotCompactTileState extends State<_SnapshotCompactTile> {
  final _q = TextEditingController(text: 'Check microfluidic channels for gas bubbles or incomplete filling.');

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final s = widget.s;
    final busy = c.snapshotAnalysisInProgress;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: LM.bg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: LM.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Text('Snapshot (${s.source}) · ${hhmmss(s.time)}',
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: LM.text)),
              const Spacer(),
              TextButton(
                onPressed: busy ? null : () => c.analyseSnapshot(s, _q.text, save: c.recordingActive),
                child: Text(c.recordingActive ? 'Analyse & Save' : 'Analyse'),
              ),
            ],
          ),
          if (s.result != null)
            Text('${s.result!['description'] ?? ''}', style: const TextStyle(fontSize: 12.5, color: LM.muted)),
          if (s.error != null)
            Text(s.error!, style: const TextStyle(fontSize: 12, color: LM.rec)),
        ],
      ),
    );
  }
}

/// Preserved ProtocolPanel widget for external callers / backward compatibility.
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
        child: Text(
          '${content['title']}',
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 11.5, color: LM.muted),
        ),
      ),
      child: Column(
        children: [
          for (final s in steps)
            ListTile(
              dense: dense,
              selected: c.highlightedStep == s['id'],
              onTap: () => c.selectProtocolStep('${s['id']}'),
              title: Text('${s['id']} · ${s['description']}', style: const TextStyle(fontSize: 13)),
            ),
        ],
      ),
    );
  }
}
