import 'package:flutter/material.dart';

import 'pages/diagnostics_page.dart';
import 'pages/feed_page.dart';
import 'pages/live_lab.dart';
import 'pages/log_page.dart';
import 'services/api.dart';
import 'services/platform_web.dart';
import 'state/app_state.dart';
import 'ui/theme.dart';

void main() {
  registerCameraView();
  final controller = AppController(
    api: LabmateApi(baseUrl: currentOrigin()), // same origin: no CORS, no mixed content
    media: WebMediaBridge(),
    socketFactory: webLiveSocketFactory,
  );
  controller.init();
  runApp(LabmateApp(controller));
}

class LabmateApp extends StatelessWidget {
  const LabmateApp(this.c, {super.key});
  final AppController c;
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'LABMATE',
        debugShowCheckedModeBanner: false,
        theme: labmateTheme(),
        home: Shell(c),
      );
}

class Shell extends StatefulWidget {
  const Shell(this.c, {super.key});
  final AppController c;
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int tab = 0;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.c,
      builder: (context, _) {
        final c = widget.c;
        if (c.requestedTab != null) {
          // Model-requested show_tab (already approved by the backend).
          final t = c.requestedTab!;
          c.requestedTab = null;
          WidgetsBinding.instance.addPostFrameCallback((_) => setState(() => tab = t));
        }
        return Scaffold(
          appBar: StatusHeader(c),
          body: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 760),
              child: IndexedStack(index: tab, children: [
                LiveLabPage(c),
                FeedPage(c),
                tab == 2 ? LogPage(c) : const SizedBox.shrink(),
                DiagnosticsPage(c),
              ]),
            ),
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: tab,
            height: 62,
            onDestinationSelected: (i) {
              setState(() => tab = i);
              c.reportTab(i);
            },
            destinations: [
              const NavigationDestination(icon: Icon(Icons.science_outlined), selectedIcon: Icon(Icons.science), label: 'Live Lab'),
              NavigationDestination(
                  icon: Badge(isLabelVisible: c.recordingActive, backgroundColor: LM.rec, smallSize: 8, child: const Icon(Icons.stream)),
                  label: 'Data feed'),
              const NavigationDestination(icon: Icon(Icons.menu_book_outlined), label: 'Experiment log'),
              const NavigationDestination(icon: Icon(Icons.monitor_heart_outlined), label: 'Diagnostics'),
            ],
          ),
        );
      },
    );
  }
}
