#!/usr/bin/env sh
#
# Wrapper used as the CXX_CLANG_TIDY / CXX_CPPCHECK launcher; analyser
# findings land in a per-source report and on the console.
#
#   analyser-launcher.sh <report-dir> <analyser> [analyser args...]
#
# CMake appends the source file and the compile command (the arguments are
# not known here); everything after <report-dir> is executed unchanged.

set -u

if [ "$#" -lt 2 ]; then
  echo "analyser-launcher.sh: usage: $0 <report-dir> <analyser> [args...]" >&2
  exit 2
fi

report_dir="$1"
shift

mkdir -p "$report_dir" || exit 1

source_file=""
previous=""
for argument in "$@"; do
  case "$argument" in
    --) source_file="$previous" ;;
    *.c|*.cc|*.cpp|*.cxx|*.C)
      if [ -z "$source_file" ]; then
        source_file="$argument"
      fi
      ;;
  esac
  previous="$argument"
done

if [ -n "$source_file" ]; then
  base=$(basename "$source_file")
  tag=$(printf '%s' "$source_file" | cksum | cut -d' ' -f1)
  report="${report_dir}/${base}.${tag}.log"
else
  report="${report_dir}/unknown-source.$$.log"
fi

output=$(mktemp "${TMPDIR:-/tmp}/analyser-launcher.XXXXXX") || exit 1

"$@" > "$output" 2>&1
status=$?

cat "$output"

if [ -s "$output" ]; then
  {
    printf 'command: %s\n' "$*"
    printf 'source:  %s\n' "${source_file:-unknown}"
    printf 'status:  %s\n\n' "$status"
    cat "$output"
  } > "$report"
else
  rm -f "$report"
fi

rm -f "$output"
exit $status
