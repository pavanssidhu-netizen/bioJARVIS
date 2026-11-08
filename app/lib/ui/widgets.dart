import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../state/app_state.dart';
import 'theme.dart';

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, required this.on, this.onColor = LM.teal, this.icon, this.pulse = false});
  final String label;
  final bool on;
  final Color onColor;
  final IconData? icon;
  final bool pulse;

  @override
  Widget build(BuildContext context) {
    final c = on ? onColor : LM.muted;
    return Semantics(
      label: '$label ${on ? 'on' : 'off'}',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: on ? onColor.withValues(alpha: 0.14) : LM.surfaceHi,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: on ? onColor.withValues(alpha: 0.6) : LM.line),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) Icon(icon, size: 13, color: c) else _Dot(color: c, pulse: on && pulse),
          const SizedBox(width: 5),
          Text(label, style: TextStyle(fontSize: 11, color: c, fontWeight: FontWeight.w600)),
        ]),
      ),
    );
  }
}

class _Dot extends StatefulWidget {
  const _Dot({required this.color, required this.pulse});
  final Color color;
  final bool pulse;
  @override
  State<_Dot> createState() => _DotState();
}

class _DotState extends State<_Dot> with SingleTickerProviderStateMixin {
  late final AnimationController _a = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));
  @override
  void didUpdateWidget(covariant _Dot old) {
    super.didUpdateWidget(old);
    widget.pulse ? _a.repeat(reverse: true) : _a.stop();
  }

  @override
  void initState() {
    super.initState();
    if (widget.pulse) _a.repeat(reverse: true);
  }

  @override
  void dispose() {
    _a.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: widget.pulse ? Tween(begin: 0.35, end: 1.0).animate(_a) : const AlwaysStoppedAnimation(1),
        child: Container(width: 8, height: 8, decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle)),
      );
}

class Panel extends StatelessWidget {
  const Panel({super.key, required this.title, required this.child, this.trailing, this.icon});
  final String title;
  final Widget child;
  final Widget? trailing;
  final IconData? icon;
  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
            color: LM.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: LM.line)),
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            if (icon != null) ...[Icon(icon, size: 16, color: LM.teal), const SizedBox(width: 8)],
            Text(title.toUpperCase(),
                style: const TextStyle(fontSize: 11, letterSpacing: 1.4, color: LM.muted, fontWeight: FontWeight.w700)),
            const Spacer(),
            ?trailing,
          ]),
          const SizedBox(height: 12),
          child,
        ]),
      );
}

class PersistenceBadge extends StatelessWidget {
  const PersistenceBadge(this.p, {super.key});
  final Persistence p;
  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (p) {
      Persistence.saved => ('SAVED', LM.ok),
      Persistence.pending => ('SAVING…', LM.warn),
      Persistence.failed => ('SAVE FAILED', LM.rec),
      Persistence.notSaved => ('NOT SAVED', LM.muted),
      Persistence.ephemeral => ('EPHEMERAL', LM.muted),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(border: Border.all(color: color.withValues(alpha: 0.7)), borderRadius: BorderRadius.circular(4)),
      child: Text(label, style: TextStyle(fontSize: 9.5, color: color, fontWeight: FontWeight.w700, letterSpacing: 0.6)),
    );
  }
}

class JsonView extends StatelessWidget {
  const JsonView(this.data, {super.key});
  final Object? data;
  @override
  Widget build(BuildContext context) {
    final text = const JsonEncoder.withIndent('  ').convert(data);
    return Stack(children: [
      Container(
        width: double.infinity,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: LM.bg, borderRadius: BorderRadius.circular(8), border: Border.all(color: LM.line)),
        child: SelectableText(text, style: const TextStyle(fontFamily: LM.mono, fontSize: 11.5, color: LM.text, height: 1.35)),
      ),
      Positioned(
        right: 2,
        top: 2,
        child: IconButton(
          tooltip: 'Copy JSON',
          iconSize: 16,
          icon: const Icon(Icons.copy, color: LM.muted),
          onPressed: () => Clipboard.setData(ClipboardData(text: text)),
        ),
      ),
    ]);
  }
}

String hhmmss(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';

IconData modalityIcon(String m) => switch (m) {
      'speech' => Icons.graphic_eq,
      'image' => Icons.image_outlined,
      'video' => Icons.visibility_outlined,
      'text' => Icons.edit_note,
      _ => Icons.memory,
    };

class FeedTile extends StatefulWidget {
  const FeedTile(this.item, {super.key});
  final FeedItem item;
  @override
  State<FeedTile> createState() => _FeedTileState();
}

class _FeedTileState extends State<FeedTile> {
  bool open = false;
  @override
  Widget build(BuildContext context) {
    final i = widget.item;
    final accent = i.isError ? LM.rec : (i.persistence == Persistence.saved ? LM.teal : LM.line);
    return InkWell(
      onTap: () => setState(() => open = !open),
      borderRadius: BorderRadius.circular(10),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: LM.surfaceHi,
          borderRadius: BorderRadius.circular(10),
          border: Border(left: BorderSide(color: accent, width: 3)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(modalityIcon(i.modality), size: 14, color: i.isError ? LM.rec : LM.teal),
            const SizedBox(width: 6),
            Text(hhmmss(i.time), style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.muted)),
            if (i.sequence != null)
              Text('  #${i.sequence}', style: const TextStyle(fontFamily: LM.mono, fontSize: 11, color: LM.muted)),
            const SizedBox(width: 8),
            Flexible(
                child: Text(i.eventType,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: LM.text))),
            const Spacer(),
            PersistenceBadge(i.persistence),
          ]),
          const SizedBox(height: 6),
          Text(i.sourceText, maxLines: open ? null : 3, overflow: open ? null : TextOverflow.ellipsis),
          if (i.model != null || i.review != 'n/a')
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                  [if (i.model != null) 'model: ${i.model}', 'modality: ${i.modality}', if (i.review != 'n/a') 'review: ${i.review}']
                      .join('  ·  '),
                  style: Theme.of(context).textTheme.bodySmall),
            ),
          if (open && (i.raw ?? i.structured) != null) ...[const SizedBox(height: 8), JsonView(i.raw ?? i.structured)],
        ]),
      ),
    );
  }
}
