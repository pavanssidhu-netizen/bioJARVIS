#!/usr/bin/env bash
# Build the Flutter web app (release) into app/build/web.
set -euo pipefail
cd "$(dirname "$0")/../app"
export PATH="${FLUTTER_ROOT:-$HOME/flutter}/bin:$PATH"
flutter pub get >/dev/null
flutter build web --release --no-web-resources-cdn --no-wasm-dry-run "$@"
echo "Built: $(pwd)/build/web"
