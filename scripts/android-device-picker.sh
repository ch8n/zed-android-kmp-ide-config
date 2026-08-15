#!/usr/bin/env bash
# Arrow-key AVD + adb picker (↑↓ move, Enter select). macOS bash 3.2 OK.
set -u

PKG="${ANDROID_APP_ID:-com.example.piximons}"
JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
export JAVA_HOME ANDROID_HOME ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:/opt/homebrew/bin:$PATH"

die() {
  [ -n "${STTY_ORIG:-}" ] && stty "$STTY_ORIG" 2>/dev/null || true
  printf '\nERROR\n%s\n\nPress Enter to close.\n' "$*"
  read -r _ < /dev/tty || true
  exit 1
}

if ! command -v adb >/dev/null || ! command -v emulator >/dev/null; then
  die "adb/emulator not on PATH. Check ANDROID_HOME=$ANDROID_HOME"
fi

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

need_cmd() { command -v "$1" >/dev/null 2>&1; }

avd_name_for_serial() {
  local serial="$1" name=""
  name="$(adb -s "$serial" emu avd name 2>/dev/null | head -1 | tr -d '\r')"
  case "$name" in
    ""|OK|KO|"unknown command"*) name="" ;;
  esac
  if [ -z "$name" ]; then
    name="$(adb -s "$serial" shell getprop ro.boot.qemu.avd_name 2>/dev/null | tr -d '\r')"
  fi
  if [ -z "$name" ]; then
    name="$(adb -s "$serial" shell getprop ro.kernel.qemu.avd_name 2>/dev/null | tr -d '\r')"
  fi
  printf '%s' "$name"
}

device_model() {
  adb -s "$1" shell getprop ro.product.model 2>/dev/null | tr -d '\r'
}

ini_get() {
  # $1 file $2 key
  [ -f "$1" ] || return 0
  awk -F= -v k="$2" '$1==k {sub(/\r$/, "", $2); print $2; exit}' "$1"
}

avd_ini() {
  printf '%s/.android/avd/%s.avd/config.ini' "$HOME" "$1"
}

pipe_join() {
  local out="" p
  for p in "$@"; do
    [ -z "$p" ] && continue
    if [ -z "$out" ]; then
      out="$p"
    else
      out="$out|$p"
    fi
  done
  printf '%s' "$out"
}

fmt_ram() {
  local n="$1"
  [ -z "$n" ] && return
  case "$n" in
    *[MmGg]) printf '%s' "$n" ;;
    *) printf '%sM' "$n" ;;
  esac
}

# api34|2G|1536M
avd_static_detail() {
  local cfg api disk ram
  cfg="$(avd_ini "$1")"
  api="$(ini_get "$cfg" target)"
  api="${api#android-}"
  disk="$(ini_get "$cfg" disk.dataPartition.size)"
  ram="$(fmt_ram "$(ini_get "$cfg" hw.ramSize)")"
  pipe_join "${api:+api${api}}" "$disk" "$ram"
}

live_detail() {
  local serial="$1" sdk disk ram kb
  [ -z "$serial" ] && return
  sdk="$(adb -s "$serial" shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')"
  disk="$(adb -s "$serial" shell df -h /data 2>/dev/null | awk 'NR==2 {print $3"/"$2}')"
  kb="$(adb -s "$serial" shell cat /proc/meminfo 2>/dev/null | awk '/MemTotal/{print int($2/1024)}')"
  [ -n "$kb" ] && ram="${kb}M"
  pipe_join "${sdk:+api${sdk}}" "$disk" "$ram"
}

row_detail() {
  local kind="$1" name="$2" state="$3" serial="$4"
  if [ "$kind" = "avd" ]; then
    avd_static_detail "$name"
    return
  fi
  if [ -n "$serial" ] && [ "$state" = "device" ]; then
    live_detail "$serial"
    return
  fi
  printf '%s' "—"
}

lookup_running() {
  local want="$1" i
  [ ${#RUN_AVD[@]} -eq 0 ] && return 1
  for i in "${!RUN_AVD[@]}"; do
    if [ "${RUN_AVD[$i]}" = "$want" ]; then
      printf '%s|%s' "${RUN_SERIAL[$i]}" "${RUN_STATE[$i]}"
      return 0
    fi
  done
  return 1
}

collect() {
  KIND=(); NAME=(); STATE=(); DETAIL=(); SERIAL=()
  RUN_AVD=(); RUN_SERIAL=(); RUN_STATE=()
  local serial state rest avd model mapped

  while read -r serial state rest; do
    [ -z "${serial:-}" ] && continue
    [ "$serial" = "List" ] && continue
    if [[ "$serial" == emulator-* ]]; then
      avd="$(avd_name_for_serial "$serial")"
      if [ -n "$avd" ]; then
        RUN_AVD+=("$avd")
        RUN_SERIAL+=("$serial")
        RUN_STATE+=("$state")
      fi
    fi
  done < <(adb devices -l | tail -n +2)

  while IFS= read -r avd; do
    [ -z "$avd" ] && continue
    mapped="$(lookup_running "$avd" || true)"
    if [ -n "$mapped" ]; then
      serial="${mapped%%|*}"
      state="${mapped#*|}"
      KIND+=("avd"); NAME+=("$avd"); STATE+=("$state")
      DETAIL+=("$(row_detail avd "$avd" "$state" "$serial")"); SERIAL+=("$serial")
    else
      KIND+=("avd"); NAME+=("$avd"); STATE+=("stopped")
      DETAIL+=("$(row_detail avd "$avd" stopped "")"); SERIAL+=("")
    fi
  done < <(emulator -list-avds 2>/dev/null)

  while read -r serial state rest; do
    [ -z "${serial:-}" ] && continue
    [ "$serial" = "List" ] && continue
    if [[ "$serial" == emulator-* ]]; then
      avd="$(avd_name_for_serial "$serial")"
      [ -n "$avd" ] && continue
      KIND+=("emu"); NAME+=("$serial"); STATE+=("$state")
      DETAIL+=("$(row_detail emu "$serial" "$state" "$serial")"); SERIAL+=("$serial")
      continue
    fi
    KIND+=("usb"); NAME+=("$serial"); STATE+=("$state")
    DETAIL+=("$(row_detail usb "$serial" "$state" "$serial")"); SERIAL+=("$serial")
  done < <(adb devices -l | tail -n +2)
}

color_state() {
  case "$1" in
    device|online) printf '%s%s%s' "$c_green" "$1" "$c_reset" ;;
    stopped) printf '%s%s%s' "$c_dim" "$1" "$c_reset" ;;
    offline|unauthorized|unknown) printf '%s%s%s' "$c_red" "$1" "$c_reset" ;;
    *) printf '%s%s%s' "$c_yellow" "$1" "$c_reset" ;;
  esac
}

# Read one key: up|down|enter|esc|quit|refresh|other
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
    n|N) echo new ;;
    d|D) echo delete ;;
    *) echo other ;;
  esac
}

draw_devices() {
  local i n=${#NAME[@]}
  printf '%s%s' "$c_clear" "$c_hide"
  printf '%sAndroid devices & emulators%s\n' "$c_bold" "$c_reset"
  printf '%s↑↓ move   Enter actions   n new   d delete   r refresh   q quit%s\n\n' "$c_dim" "$c_reset"
  if [ "$n" -eq 0 ]; then
    echo "  (none — create an AVD or plug in a device)"
    return
  fi
  printf '  %s  %-6s %-20s %-14s %s%s\n' "$c_dim" "kind" "name" "state" "detail" "$c_reset"
  for i in "${!NAME[@]}"; do
    if [ "$i" -eq "$CUR" ]; then
      printf '  %s>%s ' "$c_cyan" "$c_reset"
    else
      printf '    '
    fi
    if [ "$i" -eq "$CUR" ]; then
      printf '%s%-6s %-20s%s ' "$c_rev" "${KIND[$i]}" "${NAME[$i]}" "$c_reset"
    else
      printf '%-6s %-20s ' "${KIND[$i]}" "${NAME[$i]}"
    fi
    color_state "${STATE[$i]}"
    printf '   %s%s%s\n' "$c_dim" "${DETAIL[$i]}" "$c_reset"
  done
  echo
  printf '%sSTATUS%s  %s\n' "$c_dim" "$c_reset" "$STATUS"
}

fill_actions() {
  ACTION=()
  local kind="${KIND[$CUR]}"
  local state="${STATE[$CUR]}"
  local serial="${SERIAL[$CUR]}"
  if [ "$kind" = "avd" ] && [ "$state" = "stopped" ]; then
    ACTION+=("start")
  fi
  if [ -n "$serial" ] && [[ "$serial" == emulator-* ]] && [ "$state" = "device" ]; then
    ACTION+=("stop")
  fi
  if [ -n "$serial" ] && [ "$state" = "device" ]; then
    ACTION+=("logcat")
  fi
  ACTION+=("info")
  if [ "$kind" = "avd" ]; then
    ACTION+=("delete")
  fi
  ACTION+=("new")
  ACTION+=("back")
  ACTION+=("quit")
}

draw_actions() {
  local i
  printf '%s%s' "$c_clear" "$c_hide"
  printf '%sActions%s  %s%s%s  [%s]  %s\n' \
    "$c_bold" "$c_reset" "$c_cyan" "${NAME[$CUR]}" "$c_reset" \
    "${KIND[$CUR]}" "${STATE[$CUR]}"
  printf '%s%s%s\n' "$c_dim" "${DETAIL[$CUR]}" "$c_reset"
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

# Generic ↑↓ list. Sets PICK_INDEX. returns 1 on cancel.
pick_list() {
  local title="$1"
  shift
  local items=("$@")
  local i n=${#items[@]} cur=0
  [ "$n" -eq 0 ] && return 1
  while true; do
    printf '%s%s' "$c_clear" "$c_hide"
    printf '%s%s%s\n' "$c_bold" "$title" "$c_reset"
    printf '%s↑↓ move   Enter select   Esc cancel%s\n\n' "$c_dim" "$c_reset"
    for i in "${!items[@]}"; do
      if [ "$i" -eq "$cur" ]; then
        printf '  %s> %s%s%s\n' "$c_cyan" "$c_rev" "${items[$i]}" "$c_reset"
      else
        printf '    %s\n' "${items[$i]}"
      fi
    done
    case "$(read_key)" in
      up) [ "$cur" -gt 0 ] && cur=$((cur - 1)) ;;
      down) [ "$cur" -lt $((n - 1)) ] && cur=$((cur + 1)) ;;
      enter) PICK_INDEX=$cur; return 0 ;;
      esc|quit) return 1 ;;
    esac
  done
}

read_line() {
  # UI on stderr so $(read_line) only captures the name.
  local prompt="$1" default="$2" line=""
  printf '%s%s' "$c_clear" "$c_show" >&2
  printf '%s%s%s\n\n' "$c_bold" "$prompt" "$c_reset" >&2
  printf '%sEnter a name, or press Enter for: %s%s\n\n> ' "$c_dim" "$default" "$c_reset" >&2
  # drop leftover Enter from the previous ↑↓ menu; then read a real line from the TTY
  stty -echo -icanon min 0 time 0
  dd if=/dev/tty of=/dev/null bs=1 count=64 2>/dev/null || true
  stty echo icanon
  read -r line < /dev/tty || true
  stty -echo -icanon
  printf '%s' "$c_hide" >&2
  if [ -z "$line" ]; then
    printf '%s' "$default"
  else
    printf '%s' "$line"
  fi
}

confirm_yes() {
  pick_list "$1" "cancel" "yes, do it" || return 1
  [ "$PICK_INDEX" -eq 1 ]
}

delete_avd() {
  local name="${NAME[$CUR]}" kind="${KIND[$CUR]}" serial="${SERIAL[$CUR]}"
  if [ "$kind" != "avd" ]; then
    STATUS="delete is for emulators only"
    return
  fi
  confirm_yes "Delete AVD  $name  ?  (cannot undo)" || { STATUS="delete cancelled"; return; }
  if [ -n "$serial" ] && [[ "$serial" == emulator-* ]]; then
    adb -s "$serial" emu kill >/dev/null 2>&1 || true
    sleep 1
  fi
  if avdmanager delete avd -n "$name" >/tmp/piximon-avd-del.log 2>&1; then
    STATUS="deleted $name"
  else
    rm -rf "$HOME/.android/avd/${name}.avd" "$HOME/.android/avd/${name}.ini"
    STATUS="deleted $name (files)"
  fi
  collect
  clamp_cur
  MODE=devices
}

list_sys_images() {
  local d api tag abi
  IMG_PKG=(); IMG_LABEL=()
  [ -d "$ANDROID_HOME/system-images" ] || return
  for d in "$ANDROID_HOME"/system-images/android-*/*/*; do
    [ -d "$d" ] || continue
    abi="$(basename "$d")"
    tag="$(basename "$(dirname "$d")")"
    api="$(basename "$(dirname "$(dirname "$d")")")"
    IMG_PKG+=("system-images;${api};${tag};${abi}")
    IMG_LABEL+=("${api}  ${tag}  ${abi}")
  done
}

write_avd() {
  local name="$1" pkg="$2" profile="$3"
  local api tag abi target ram disk w h den cores play
  # pkg: system-images;android-34;google_apis;arm64-v8a
  api="$(printf '%s' "$pkg" | awk -F';' '{print $2}')"
  tag="$(printf '%s' "$pkg" | awk -F';' '{print $3}')"
  abi="$(printf '%s' "$pkg" | awk -F';' '{print $4}')"
  target="$api"
  if [ "$profile" = "medium" ]; then
    ram=2048; disk=6G; w=1080; h=2400; den=420; cores=4
  else
    ram=1536; disk=2G; w=720; h=1280; den=320; cores=2
  fi
  play=false
  case "$tag" in *playstore*) play=true ;; esac

  mkdir -p "$HOME/.android/avd/${name}.avd"
  cat > "$HOME/.android/avd/${name}.ini" <<EOF
avd.ini.encoding=UTF-8
path=$HOME/.android/avd/${name}.avd
path.rel=avd/${name}.avd
target=${target}
EOF
  cat > "$HOME/.android/avd/${name}.avd/config.ini" <<EOF
AvdId=${name}
PlayStore.enabled=${play}
abi.type=${abi}
avd.ini.displayname=${name}
avd.ini.encoding=UTF-8
disk.dataPartition.size=${disk}
fastboot.forceColdBoot=yes
fastboot.forceFastBoot=no
hw.audioInput=no
hw.audioOutput=no
hw.battery=yes
hw.camera.back=none
hw.camera.front=none
hw.cpu.arch=arm64
hw.cpu.ncore=${cores}
hw.device.name=${profile}_phone
hw.gps=no
hw.gpu.enabled=yes
hw.gpu.mode=host
hw.keyboard=yes
hw.lcd.density=${den}
hw.lcd.height=${h}
hw.lcd.width=${w}
hw.ramSize=${ram}
hw.sdCard=no
image.sysdir.1=system-images/${api}/${tag}/${abi}/
showDeviceFrame=no
tag.id=${tag}
tag.ids=${tag}
target=${target}
vm.heapSize=128
EOF
}

create_avd_flow() {
  local name profile pkg
  list_sys_images
  if [ ${#IMG_LABEL[@]} -eq 0 ]; then
    STATUS="no system images installed"
    return
  fi
  pick_list "New emulator — system image" "${IMG_LABEL[@]}" || { STATUS="create cancelled"; return; }
  pkg="${IMG_PKG[$PICK_INDEX]}"
  pick_list "New emulator — profile" "small (lite 720p 1536M 2G)" "medium (1080p 2048M 6G)" || { STATUS="create cancelled"; return; }
  if [ "$PICK_INDEX" -eq 1 ]; then profile=medium; else profile=small; fi
  name="$(read_line "AVD name (letters, numbers, _ )" "${profile}_phone")"
  name="$(printf '%s' "$name" | tr -cd 'A-Za-z0-9_')"
  if [ -z "$name" ]; then
    STATUS="invalid name"
    return
  fi
  if [ -e "$HOME/.android/avd/${name}.ini" ]; then
    confirm_yes "AVD $name exists. Overwrite?" || { STATUS="create cancelled"; return; }
    avdmanager delete avd -n "$name" >/dev/null 2>&1 || rm -rf "$HOME/.android/avd/${name}.avd" "$HOME/.android/avd/${name}.ini"
  fi
  write_avd "$name" "$pkg" "$profile"
  collect
  clamp_cur
  local i
  for i in "${!NAME[@]}"; do
    [ "${NAME[$i]}" = "$name" ] && CUR=$i
  done
  STATUS="created $name"
  MODE=devices
}

avd_is_up() {
  local want="$1" i
  for i in "${!NAME[@]}"; do
    if [ "${NAME[$i]}" = "$want" ] && [ "${STATE[$i]}" = "device" ]; then
      printf '%s' "${SERIAL[$i]}"
      return 0
    fi
  done
  return 1
}

start_avd() {
  local avd="$1" log epid serial i last
  log="/tmp/piximon-emu-${avd}.log"
  STATUS="starting $avd (lite)…"
  draw_devices
  # Detach from the picker's raw TTY / process group. Inheriting stdin or
  # staying in Zed's task group makes the emulator exit immediately.
  : >"$log"
  nohup emulator -avd "$avd" -no-audio -no-boot-anim -gpu host -accel on \
    -no-snapshot-load -no-snapshot-save -no-metrics \
    </dev/null >>"$log" 2>&1 &
  epid=$!
  disown "$epid" 2>/dev/null || true
  echo "$epid" >"/tmp/piximon-emu-${avd}.pid"
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    sleep 2
    collect
    if serial="$(avd_is_up "$avd")"; then
      STATUS="$avd is up ($serial)"
      return
    fi
    if ! kill -0 "$epid" 2>/dev/null; then
      last="$(tail -5 "$log" 2>/dev/null | tr '\n' ' ')"
      STATUS="emulator exited (pid $epid). $last"
      return
    fi
    STATUS="booting $avd… ($i)  log $log"
    draw_devices
  done
  STATUS="still booting — check emulator window / $log"
}

stop_emu() {
  local serial="$1" name="$2"
  STATUS="stopping $name…"
  draw_devices
  adb -s "$serial" emu kill >/dev/null 2>&1 || true
  sleep 1
  collect
  clamp_cur
  STATUS="stopped $name"
}

show_info() {
  local name="${NAME[$CUR]}" kind="${KIND[$CUR]}" serial="${SERIAL[$CUR]}"
  local cfg info=""
  printf '%s%s' "$c_clear" "$c_hide"
  printf '%sDevice info%s  %s\n\n' "$c_bold" "$c_reset" "$name"
  printf '  %s\n\n' "${DETAIL[$CUR]}"
  if [ "$kind" = "avd" ]; then
    cfg="$(avd_ini "$name")"
    if [ -f "$cfg" ]; then
      printf '%sAVD config%s\n' "$c_dim" "$c_reset"
      printf '  target    %s\n' "$(ini_get "$cfg" target)"
      printf '  disk      %s\n' "$(ini_get "$cfg" disk.dataPartition.size)"
      printf '  ram       %s\n' "$(fmt_ram "$(ini_get "$cfg" hw.ramSize)")"
      printf '  abi       %s\n' "$(ini_get "$cfg" abi.type)"
      printf '  tag       %s\n' "$(ini_get "$cfg" tag.id)"
      printf '  lcd       %sx%s\n' "$(ini_get "$cfg" hw.lcd.width)" "$(ini_get "$cfg" hw.lcd.height)"
      echo
    fi
  fi
  if [ -n "$serial" ] && [ "${STATE[$CUR]}" = "device" ]; then
    printf '%slive%s  %s\n' "$c_dim" "$c_reset" "$serial"
    printf '  model     %s\n' "$(adb -s "$serial" shell getprop ro.product.model | tr -d '\r')"
    printf '  android   %s (api %s)\n' \
      "$(adb -s "$serial" shell getprop ro.build.version.release | tr -d '\r')" \
      "$(adb -s "$serial" shell getprop ro.build.version.sdk | tr -d '\r')"
    printf '  abi       %s\n' "$(adb -s "$serial" shell getprop ro.product.cpu.abi | tr -d '\r')"
    printf '  /data     %s\n' "$(adb -s "$serial" shell df -h /data | awk 'NR==2{print $3" used / "$2"  ("$4" free)"}')"
    adb -s "$serial" shell dumpsys battery 2>/dev/null | awk '/level:|status:/{print "  battery   "$0}'
    echo
  fi
  printf '%sEnter / Esc back%s\n' "$c_dim" "$c_reset"
  while true; do
    case "$(read_key)" in
      enter|esc|quit) return ;;
    esac
  done
}

run_logcat() {
  local serial="$1"
  cleanup
  STTY_ORIG=""
  printf '%s%s' "$c_clear" "$c_show"
  echo "pidcat $PKG  ($serial)   Ctrl+C to stop"
  echo
  if need_cmd pidcat; then
    exec pidcat -s "$serial" -c "$PKG"
  fi
  exec adb -s "$serial" logcat -v color
}

clamp_cur() {
  local n=${#NAME[@]}
  [ "$n" -eq 0 ] && CUR=0 && return
  [ "$CUR" -lt 0 ] && CUR=0
  [ "$CUR" -ge "$n" ] && CUR=$((n - 1))
}

run_action() {
  local act="${ACTION[$ACUR]}"
  local kind="${KIND[$CUR]}"
  local name="${NAME[$CUR]}"
  local state="${STATE[$CUR]}"
  local serial="${SERIAL[$CUR]}"
  case "$act" in
    start) start_avd "$name"; MODE=devices ;;
    stop) stop_emu "$serial" "$name"; MODE=devices ;;
    logcat) run_logcat "$serial" ;;
    info) show_info ;;
    delete) delete_avd ;;
    new) create_avd_flow ;;
    back) MODE=devices ;;
    quit) exit 0 ;;
  esac
}

main() {
  if [ ! -t 0 ]; then
    die "Need an interactive terminal (run from Zed task / a real TTY)."
  fi
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
      esc|left)
        MODE=devices
        ;;
      refresh)
        collect
        clamp_cur
        STATUS="refreshed"
        ;;
      new)
        create_avd_flow
        ;;
      delete)
        if [ ${#NAME[@]} -gt 0 ]; then
          delete_avd
        fi
        ;;
      quit)
        exit 0
        ;;
    esac
  done
}

main
