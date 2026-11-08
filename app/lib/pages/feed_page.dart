import 'package:flutter/material.dart';

import '../state/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class FeedPage extends StatefulWidget {
  const FeedPage(this.c, {super.key});
  final AppController c;
  @override
  State<FeedPage> createState() => _FeedPageState();
}

class _FeedPageState extends State<FeedPage> {
  String filter = 'All';
  static const filters = ['All', 'Speech', 'Vision', 'Observations', 'Errors'];

  bool _match(FeedItem i) => switch (filter) {
        'Speech' => i.modality == 'speech',
        'Vision' => i.modality == 'image' || i.modality == 'video',
        'Observations' => const {'observation_proposal', 'visual_observation', 'perception', 'correction'}.contains(i.eventType),
        'Errors' => i.isError,
        _ => true,
      };

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final items = c.feed.where(_match).toList();
    return Column(children: [
      if (!c.recordingActive)
        Container(
          width: double.infinity,
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: LM.surfaceHi, borderRadius: BorderRadius.circular(10), border: Border.all(color: LM.line)),
          child: const Row(children: [
            Icon(Icons.pause_circle_outline, color: LM.muted, size: 18),
            SizedBox(width: 8),
            Expanded(child: Text('Recording paused — new speech is shown here but not saved.', style: TextStyle(color: LM.muted))),
          ]),
        ),
      SizedBox(
        height: 40,
        child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
          for (final f in filters)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(label: Text(f), selected: filter == f, onSelected: (_) => setState(() => filter = f)),
            ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(14, 4, 14, 4),
        child: Row(children: [
          Text('${items.length} events · last seq #${c.lastSeq}', style: Theme.of(context).textTheme.bodySmall),
          const Spacer(),
          Text('tap to inspect JSON', style: Theme.of(context).textTheme.bodySmall),
        ]),
      ),
      Expanded(
        child: items.isEmpty
            ? const Center(child: Text('Nothing here yet.', style: TextStyle(color: LM.muted)))
            : ListView.builder(
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                itemCount: items.length,
                itemBuilder: (_, i) => FeedTile(items[i], key: ValueKey(items[i].key)),
              ),
      ),
    ]);
  }
}
