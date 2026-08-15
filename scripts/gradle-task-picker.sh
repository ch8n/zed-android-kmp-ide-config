#!/usr/bin/env bash
# Arrow-key Gradle task picker (type to filter, ↑↓, Enter run). macOS bash 3.2 OK.
set -u

JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
export JAVA_HOME
export PATH="$JAVA_HOME/bin:/opt/homebrew/bin:$PATH"

c_reset=$'\033[0m'
c_dim=$'\033[2m'
c_bold=$'\033[1m'
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
  [ -n "${STTY_ORIG:-}" ] && stty "$STTY_ORIG" 2>/dev/null || true
  printf '%s' "$c_show"
  printf '\nERROR\n%s\n\nPress Enter to close.\n' "$*"
  read -r _ < /dev/tty || true
  exit 1
}

find_root() {
  local d="${1:-$PWD}"
  while [ "$d" != "/" ]; do
    [ -x "$d/gradlew" ] && { printf '%s' "$d"; return 0; }
    d="$(dirname "$d")"
  done
  return 1
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
        *) echo esc ;;
      esac
      return
    fi
    echo esc
    return
  fi
  case "$k" in
    ""|$'\n'|$'\r') echo enter ;;
    $'\x7f'|$'\x08') echo backspace ;;
    $'\x15') echo clearfilter ;;
    $'\x12') echo refresh ;;
    *)
      case "$k" in
        [[:print:]]) echo "type:$k" ;;
        *) echo other ;;
      esac
      ;;
  esac
}

# Must not run in a pipeline (bash 3.2: functions in | are a subshell — arrays vanish).
parse_tasks_file() {
  TASK=(); DESC=()
  local line name rest
  [ -f "$1" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ""|---*|"> "*|"> Task"*|Calculating\ *|WARNING:*|The\ current\ *) continue ;;
      *" tasks"|Tasks\ *|To\ see\ *|For\ more\ *) continue ;;
    esac
    if [ "${line#* - }" != "$line" ]; then
      name="${line%% - *}"
      rest="${line#* - }"
    else
      name="$line"
      rest=""
    fi
    name="${name%"${name##*[![:space:]]}"}"
    case "$name" in
      ""|*[[:space:]]*) continue ;;
    esac
    case "$name" in
      *[!A-Za-z0-9:_]*) continue ;;
    esac
    TASK+=("$name")
    DESC+=("$rest")
  done < "$1"
  build_hay
}

# Lowercase index — bash 3.2 typeset -l, no tr/forks per keystroke.
build_hay() {
  HAY=()
  local i
  typeset -l row
  for i in "${!TASK[@]}"; do
    row="${TASK[$i]} ${DESC[$i]}"
    HAY+=("$row")
  done
}

apply_filter() {
  VIEW=()
  local i n
  typeset -l needle
  needle="$FILTER"
  if [ -z "$needle" ]; then
    for i in "${!TASK[@]}"; do
      VIEW+=("$i")
    done
  else
    for i in "${!HAY[@]}"; do
      case "${HAY[$i]}" in
        *"$needle"*) VIEW+=("$i") ;;
      esac
    done
  fi
  n=${#VIEW[@]}
  [ "$n" -eq 0 ] && CUR=0 && return
  [ "$CUR" -lt 0 ] && CUR=0
  [ "$CUR" -ge "$n" ] && CUR=$((n - 1))
}

load_cache() {
  TASK=(); DESC=()
  [ -f "$CACHE" ] || return 1
  local line name desc
  while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    name="${line%%	*}"
    desc="${line#*	}"
    TASK+=("$name")
    DESC+=("$desc")
  done < "$CACHE"
  build_hay
  [ ${#TASK[@]} -gt 0 ]
}

save_cache() {
  mkdir -p "$ROOT/.gradle"
  local i
  : > "$CACHE"
  for i in "${!TASK[@]}"; do
    printf '%s\t%s\n' "${TASK[$i]}" "${DESC[$i]}" >> "$CACHE"
  done
}

load_tasks() {
  local raw="/tmp/zed-android-gradle-tasks.out"
  STATUS="loading ./gradlew tasks --all…"
  draw
  if ! "$ROOT/gradlew" -p "$ROOT" tasks --all --console=plain \
      >"$raw" 2>/tmp/zed-android-gradle-tasks.err; then
    STATUS="gradlew tasks failed — /tmp/zed-android-gradle-tasks.err"
    TASK=(); DESC=()
    apply_filter
    return 1
  fi
  parse_tasks_file "$raw"
  save_cache
  STATUS="loaded ${#TASK[@]} tasks"
  apply_filter
}

draw() {
  local i n=${#VIEW[@]} idx max=18 start=0
  printf '%s%s' "$c_clear" "$c_hide"
  printf '%sGradle tasks%s\n' "$c_bold" "$c_reset"
  printf '%stype to filter   ↑↓ select   Enter run   Ctrl+R refresh   Ctrl+U clear   Esc quit%s\n' \
    "$c_dim" "$c_reset"
  printf '  filter: %s%s%s_\n\n' "$c_cyan" "$FILTER" "$c_reset"

  if [ ${#TASK[@]} -eq 0 ]; then
    printf '  (no tasks loaded)\n\n'
    printf '%sSTATUS%s  %s\n' "$c_dim" "$c_reset" "$STATUS"
    return
  fi

  if [ "$n" -eq 0 ]; then
    printf '  (no match for "%s")\n\n' "$FILTER"
    printf '%sSTATUS%s  %s  (%s total)\n' "$c_dim" "$c_reset" "$STATUS" "${#TASK[@]}"
    return
  fi

  if [ "$n" -gt "$max" ]; then
    start=$((CUR - max / 2))
    [ "$start" -lt 0 ] && start=0
    [ $((start + max)) -gt "$n" ] && start=$((n - max))
  fi

  i=$start
  while [ "$i" -lt "$n" ] && [ "$i" -lt $((start + max)) ]; do
    idx="${VIEW[$i]}"
    if [ "$i" -eq "$CUR" ]; then
      printf '  %s>%s %s%-36s%s %s%s%s\n' \
        "$c_cyan" "$c_reset" "$c_rev" "${TASK[$idx]}" "$c_reset" \
        "$c_dim" "${DESC[$idx]}" "$c_reset"
    else
      printf '    %-36s %s%s%s\n' "${TASK[$idx]}" "$c_dim" "${DESC[$idx]}" "$c_reset"
    fi
    i=$((i + 1))
  done
  echo
  printf '%s%s matches  %s total%s\n' "$c_dim" "$n" "${#TASK[@]}" "$c_reset"
  printf '%sSTATUS%s  %s\n' "$c_dim" "$c_reset" "$STATUS"
}

run_selected() {
  local n=${#VIEW[@]} idx task
  [ "$n" -eq 0 ] && return
  idx="${VIEW[$CUR]}"
  task="${TASK[$idx]}"
  cleanup
  STTY_ORIG=""
  printf '%s%s' "$c_clear" "$c_show"
  echo "+ $ROOT/gradlew -p $ROOT $task"
  echo
  if ! "$ROOT/gradlew" -p "$ROOT" "$task"; then
    die "./gradlew $task failed (exit $?)"
  fi
  exit 0
}

main() {
  if [ ! -t 0 ]; then
    die "Need an interactive terminal (run from Zed task / a real TTY)."
  fi
  ROOT="$(find_root "${1:-$PWD}")" || {
    die "No gradlew found walking up from ${1:-$PWD}"
  }
  CACHE="$ROOT/.gradle/android-ide-gradle-tasks.cache"

  STTY_ORIG="$(stty -g)"
  stty -echo -icanon
  CUR=0
  FILTER=""
  STATUS="ready"
  TASK=(); DESC=(); VIEW=()

  if load_cache; then
    STATUS="cached ${#TASK[@]} tasks  (Ctrl+R to refresh)"
    apply_filter
  else
    load_tasks
  fi

  local key ch
  while true; do
    draw
    key="$(read_key)"
    case "$key" in
      up) [ "$CUR" -gt 0 ] && CUR=$((CUR - 1)) ;;
      down)
        [ ${#VIEW[@]} -gt 0 ] && [ "$CUR" -lt $((${#VIEW[@]} - 1)) ] && CUR=$((CUR + 1))
        ;;
      enter) run_selected ;;
      refresh) load_tasks ;;
      backspace)
        [ -n "$FILTER" ] && FILTER="${FILTER%?}"
        CUR=0
        apply_filter
        ;;
      clearfilter)
        FILTER=""
        CUR=0
        apply_filter
        ;;
      esc)
        if [ -n "$FILTER" ]; then
          FILTER=""
          CUR=0
          apply_filter
        else
          exit 0
        fi
        ;;
      type:*)
        ch="${key#type:}"
        FILTER="${FILTER}${ch}"
        CUR=0
        apply_filter
        ;;
    esac
  done
}

main "$@"
