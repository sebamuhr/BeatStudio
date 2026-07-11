#!/usr/bin/env bash
# Install the Beat Studio launcher into the app menu and onto the Desktop.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/BeatStudio.desktop"

# App menu
mkdir -p "$HOME/.local/share/applications"
cp "$SRC" "$HOME/.local/share/applications/BeatStudio.desktop"
chmod +x "$HOME/.local/share/applications/BeatStudio.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# Desktop icon
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
mkdir -p "$DESK"
cp "$SRC" "$DESK/BeatStudio.desktop"
chmod +x "$DESK/BeatStudio.desktop"
# GNOME/Nautilus: mark trusted so double-click launches instead of opening as text
gio set "$DESK/BeatStudio.desktop" metadata::trusted true 2>/dev/null || true

echo "Installed. Look for 'Beat Studio' in your apps menu and on your Desktop."
