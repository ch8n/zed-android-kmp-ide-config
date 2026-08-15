#!/usr/bin/env bash
# Arrow-key iOS Simulator picker. Uses existing Xcode/simctl only — never installs.
set -u

c_reset=$'\033[0m'
c_dim=$'\033[2m'
c_bold=$'\033[1m'
c_green=$'\033[32m'
c_yellow=$'\033[33m'
c_red=$'\033[31m'
c_cyan=$'\033[36m'
c_rev=$'\033[7m'
c_hide=$'\033[?25l'
c_show=$'\033[?25h'
c_clear=$'\033[2J\033[H'

STTY_ORIG=""
cleanup() {
  [ -n "$STTY_ORIG" ] && stty "$STTY_ORIG" 2>/dev/null || true
  printf '%s' "$c_show"
}
trap cleanup EXIT INT TERM

die() {
  [ -n "$STTY_ORIG" ] && stty "$STTY_ORIG" 2>/dev/null || true
  printf '%s' "$c_show"
  printf '\n%sERROR%s\n' "$c_red" "$c_reset"
  printf '%s\n' "$@"
  echo
  echo "Press Enter to close."
  read -r _ < /dev/tty || true
  exit 1
}

need_xcode() {
  local err
  if ! command -v xcrun >/dev/null 2>&1; then
    die "xcrun not found." \
      "Install Xcode from the App Store if you need iOS sims." \
      "(This script will not install or update Xcode.)"
  fi
  if ! err="$(xcrun simctl help 2>&1)"; then
    die "simctl unavailable (xcrun simctl failed)." \
      "$err" \
      "" \
      "Xcode / Command Line Tools may be missing or not selected." \
      "  xcode-select -p" \
      "(This script will not install or update Xcode.)"
  fi
}

read_key() {
  local k rest
  IFS= read -rsn1 k || true
  if [ "$k" = $'\x1b' ]; then
    IFS= read -rsn1 -t 1 rest || { echo esc; return; }
    if [ "$rest" = "[" ]; then
      IFS= read -rsn1 rest || true
      case "$rest" in
        A) echo up ;;
        B) echo down ;;
        C) echo right ;;
        D) echo left ;;
        *) echo esc ;;
      esac
      return
    fi
    echo esc
    return
  fi
  case "$k" in
    ""|$'\n'|$'\r') echo enter ;;
    q|Q) echo quit ;;
    r|R) echo refresh ;;
    *) echo other ;;
  esac
}

# NAME[] OS[] UDID[] STATE[]
collect() {
  NAME=(); OS=(); UDID=(); STATE=()
  local line os="" name udid state
  # available devices only; do not trigger downloads
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      --*)
        os="${line#-- }"
        os="${os% --}"
        ;;
      *)
        # "    iPhone 16 (UUID) (Shutdown)"
        name="$(printf '%s' "$line" | sed -n 's/^[[:space:]]*\(.*\) ([0-9A-Fa-f-]\{36\}) (\([^)]*\)).*/\1/p')"
        udid="$(printf '%s' "$line" | sed -n 's/.*(\([0-9A-Fa-f-]\{36\}\)).*/\1/p')"
        state="$(printf '%s' "$line" | sed -n 's/.*(\([0-9A-Fa-f-]\{36\}\)) (\([^)]*\)).*/\2/p')"
        [ -z "$udid" ] && continue
        NAME+=("$name")
        OS+=("$os")
        UDID+=("$udid")
        STATE+=("$state")
        ;;
    esac
  done < <(xcrun simctl list devices available 2>/dev/null)
}

color_state() {
  case "$1" in
    Booted) printf '%s%s%s' "$c_green" "$1" "$c_reset" ;;
    Shutdown) printf '%s%s%s' "$c_dim" "$1" "$c_reset" ;;
    Booting|Creating|Checking) printf '%s%s%s' "$c_yellow" "$1" "$c_reset" ;;
    *) printf '%s%s%s' "$c_red" "$1" "$c_reset" ;;
  esac
}

draw_devices() {
  local i n=${#NAME[@]}
  printf '%s%s' "$c_clear" "$c_hide"
  printf '%siOS simulators%s\n' "$c_bold" "$c_reset"
  printf '%s↑↓ move   Enter actions   r refresh   q quit%s\n' "$c_dim" "$c_reset"
  printf '%s(uses existing Xcode/simctl only — will not install runtimes)%s\n\n' "$c_dim" "$c_reset"
  if [ "$n" -eq 0 ]; then
    echo "  (none available — install a simulator in Xcode yourself)"
    echo
    printf '%sSTATUS%s  %s\n' "$c_dim" "$c_reset" "$STATUS"
    return
  fi
  printf '  %s  %-28s %-16s %s%s\n' "$c_dim" "name" "os" "state" "$c_reset"
  for i in "${!NAME[@]}"; do
    if [ "$i" -eq "$CUR" ]; then
      printf '  %s>%s %s%-28s%s %-16s ' "$c_cyan" "$c_reset" "$c_rev" "${NAME[$i]}" "$c_reset" "${OS[$i]}"
    else
      printf '    %-28s %-16s ' "${NAME[$i]}" "${OS[$i]}"
    fi
    color_state "${STATE[$i]}"
    printf '\n'
  done
  echo
  printf '%sSTATUS%s  %s\n' "$c_dim" "$c_reset" "$STATUS"
}

fill_actions() {
  ACTION=()
  local state="${STATE[$CUR]}"
  if [ "$state" != "Booted" ]; then
    ACTION+=("boot")
  fi
  if [ "$state" = "Booted" ]; then
    ACTION+=("shutdown")
    ACTION+=("open-ui")
  fi
  ACTION+=("info")
  ACTION+=("back")
  ACTION+=("quit")
}

draw_actions() {
  local i
  printf '%s%s' "$c_clear" "$c_hide"
  printf '%sActions%s  %s%s%s  [%s]  %s\n' \
    "$c_bold" "$c_reset" "$c_cyan" "${NAME[$CUR]}" "$c_reset" \
    "${OS[$CUR]}" "${STATE[$CUR]}"
  printf '%s%s%s\n' "$c_dim" "${UDID[$CUR]}" "$c_reset"
  printf '%s↑↓ move   Enter run   Esc back   q quit%s\n\n' "$c_dim" "$c_reset"
  for i in "${!ACTION[@]}"; do
    if [ "$i" -eq "$ACUR" ]; then
      printf '  %s> %s%s%s\n' "$c_cyan" "$c_rev" "${ACTION[$i]}" "$c_reset"
    else
      printf '    %s\n' "${ACTION[$i]}"
    fi
  done
  echo
  printf '%sSTATUS%s  %s\n' "$c_dim" "$c_reset" "$STATUS"
}

clamp_cur() {
  local n=${#NAME[@]}
  [ "$n" -eq 0 ] && CUR=0 && return
  [ "$CUR" -lt 0 ] && CUR=0
  [ "$CUR" -ge "$n" ] && CUR=$((n - 1))
}

show_info() {
  printf '%s%s' "$c_clear" "$c_hide"
  printf '%sSimulator info%s\n\n' "$c_bold" "$c_reset"
  printf '  name   %s\n' "${NAME[$CUR]}"
  printf '  os     %s\n' "${OS[$CUR]}"
  printf '  state  %s\n' "${STATE[$CUR]}"
  printf '  udid   %s\n\n' "${UDID[$CUR]}"
  xcrun simctl getenv "${UDID[$CUR]}" SIMULATOR_DEVICE_NAME >/dev/null 2>&1 || true
  printf '%sEnter / Esc back%s\n' "$c_dim" "$c_reset"
  while true; do
    case "$(read_key)" in
      enter|esc|quit) return ;;
    esac
  done
}

boot_sim() {
  local udid="$1" name="$2"
  STATUS="booting $name…"
  draw_devices
  if xcrun simctl boot "$udid" >/tmp/zed-android-simctl.log 2>&1; then
    # Open Simulator.app only if already installed — never trigger a download.
    if [ -d /Applications/Xcode.app ] || [ -d /Applications/Xcode-beta.app ]; then
      open -a Simulator >/dev/null 2>&1 || true
    fi
    STATUS="booted $name"
  else
    STATUS="boot failed — /tmp/zed-android-simctl.log"
  fi
  collect
  clamp_cur
}

shutdown_sim() {
  local udid="$1" name="$2"
  STATUS="shutting down $name…"
  draw_devices
  if xcrun simctl shutdown "$udid" >/tmp/zed-android-simctl.log 2>&1; then
    STATUS="shutdown $name"
  else
    STATUS="shutdown failed — /tmp/zed-android-simctl.log"
  fi
  collect
  clamp_cur
}

open_ui() {
  if [ -d /Applications/Xcode.app ] || [ -d /Applications/Xcode-beta.app ]; then
    open -a Simulator >/dev/null 2>&1 || STATUS="could not open Simulator.app"
    STATUS="opened Simulator.app"
  else
    STATUS="Simulator.app not installed (will not download Xcode)"
  fi
}

run_action() {
  local act="${ACTION[$ACUR]}"
  local name="${NAME[$CUR]}"
  local udid="${UDID[$CUR]}"
  case "$act" in
    boot) boot_sim "$udid" "$name"; MODE=devices ;;
    shutdown) shutdown_sim "$udid" "$name"; MODE=devices ;;
    open-ui) open_ui ;;
    info) show_info ;;
    back) MODE=devices ;;
    quit) exit 0 ;;
  esac
}

main() {
  if [ ! -t 0 ]; then
    die "Need an interactive terminal (run from Zed task / a real TTY)."
  fi
  need_xcode
  STTY_ORIG="$(stty -g)"
  stty -echo -icanon
  CUR=0
  ACUR=0
  MODE=devices
  STATUS="ready"
  collect
  clamp_cur

  while true; do
    if [ "$MODE" = "devices" ]; then
      draw_devices
    else
      [ ${#NAME[@]} -eq 0 ] && MODE=devices && continue
      fill_actions
      [ ${#ACTION[@]} -eq 0 ] && MODE=devices && continue
      [ "$ACUR" -ge ${#ACTION[@]} ] && ACUR=$((${#ACTION[@]} - 1))
      [ "$ACUR" -lt 0 ] && ACUR=0
      draw_actions
    fi

    case "$(read_key)" in
      up)
        if [ "$MODE" = "devices" ]; then
          [ "$CUR" -gt 0 ] && CUR=$((CUR - 1))
        else
          [ "$ACUR" -gt 0 ] && ACUR=$((ACUR - 1))
        fi
        ;;
      down)
        if [ "$MODE" = "devices" ]; then
          [ ${#NAME[@]} -gt 0 ] && [ "$CUR" -lt $((${#NAME[@]} - 1)) ] && CUR=$((CUR + 1))
        else
          [ "$ACUR" -lt $((${#ACTION[@]} - 1)) ] && ACUR=$((ACUR + 1))
        fi
        ;;
      enter)
        if [ "$MODE" = "devices" ]; then
          [ ${#NAME[@]} -eq 0 ] && continue
          ACUR=0
          MODE=actions
        else
          run_action
        fi
        ;;
      esc|left) MODE=devices ;;
      refresh)
        collect
        clamp_cur
        STATUS="refreshed"
        ;;
      quit) exit 0 ;;
    esac
  done
}

main
