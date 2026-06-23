#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${IOS_PROJECT:-$ROOT/JustPickThisIOS.xcodeproj}"
SCHEME="${IOS_SCHEME:-JustPickThisIOS}"
CONFIGURATION="${IOS_CONFIGURATION:-Debug}"

if [[ ! -d "$PROJECT" ]]; then
  echo "Xcode project not found: $PROJECT" >&2
  exit 1
fi

destination_id="${IOS_SIMULATOR_ID:-}"
if [[ -z "$destination_id" ]]; then
  destination_id="$(
    xcodebuild -project "$PROJECT" -scheme "$SCHEME" -showdestinations 2>/dev/null \
      | awk '
          /platform:iOS Simulator/ && /name:iPhone/ && $0 !~ /placeholder/ {
            if (match($0, /id:[^,}]+/)) {
              print substr($0, RSTART + 3, RLENGTH - 3)
              exit
            }
          }
        '
  )"
fi

if [[ -z "$destination_id" ]]; then
  echo "No available iPhone simulator destination found. Open Xcode once or install an iOS Simulator runtime." >&2
  exit 2
fi

echo "Building $SCHEME ($CONFIGURATION) for simulator id=$destination_id"
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -destination "id=$destination_id" \
  build
