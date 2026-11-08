/// Platform abstractions. The browser implementations live in platform_web.dart; tests inject fakes.
abstract class MediaBridge {
  /// Must be called from a user gesture (Connect button) so iOS/Safari allow playback.
  void unlockAudio();
  void playPcm(String b64, int rate);
  void stopPlayback();

  /// Starts mic capture; emits base64 16 kHz PCM16 chunks (~100 ms). Throws if permission denied.
  Future<void> micStart(void Function(String b64) onChunk, void Function(double rms) onLevel);
  void micStop();
  bool micActive();

  Future<void> cameraOpen(String facing);
  void cameraClose();
  bool cameraActive();
  String cameraTrackStates();
  Future<bool> hasMultipleCameras();
  String? captureFrame(int maxWidth, double quality);

  /// Width/height of the live camera video (0 if unknown) - maps box_2d tags onto the preview.
  double videoAspect();

  Future<String> permission(String name);
  void pickImage(void Function(String b64) onPicked);
  void downloadJson(String filename, String text);
  bool beacon(String url);
  void onPageHide(void Function() cb);
  void stopAll();
}

abstract class LiveSocket {
  void send(String data);
  void close([int code = 1000, String reason = '']);
}

typedef LiveSocketFactory = LiveSocket Function(
  String url, {
  required void Function() onOpen,
  required void Function(String data) onMessage,
  required void Function(int code, String reason) onClose,
});
