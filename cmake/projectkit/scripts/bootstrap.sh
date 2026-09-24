#!/usr/bin/env bash
#
# Rename of a project created from the template: directories, file names and
# file contents, in that order.
#
#   ./scripts/bootstrap.sh myproject
#   ./scripts/bootstrap.sh myproject --description="A thing" --version=0.1.0
#   ./scripts/bootstrap.sh myproject --dry-run
#
# The cmake/projectkit/ directory is never changed because nothing in it uses a
# specific project name. Git is how you undo; the script won't run on a dirty
# git repository tree unless the --force flag is given.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pk_find_repo_root() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "${dir}/CMakeLists.txt" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

if [[ -z "${PK_REPO_ROOT:-}" ]]; then
  PK_REPO_ROOT="$(pk_find_repo_root)" || {
    printf 'no CMakeLists.txt found above %s: set PK_REPO_ROOT\n' "$PWD" >&2
    exit 2
  }
fi

if [[ -t 1 ]]; then
  PK_BOLD=$'\033[1m'; PK_RED=$'\033[31m'; PK_GREEN=$'\033[32m'
  PK_YELLOW=$'\033[33m'; PK_RESET=$'\033[0m'
else
  PK_BOLD=""; PK_RED=""; PK_GREEN=""; PK_YELLOW=""; PK_RESET=""
fi

pk_die() { printf '%serror%s  %s\n' "$PK_RED" "$PK_RESET" "$1" >&2; exit 1; }
pk_note() { printf '%s--%s %s\n' "$PK_BOLD" "$PK_RESET" "$1"; }
pk_warn() { printf '%swarning%s  %s\n' "$PK_YELLOW" "$PK_RESET" "$1"; }

usage() {
  cat <<USAGE
usage: $(basename "$0") <new-name> [flag...]

Renames every directory, file name and file content occurrence of the current
project name. The kit under cmake/projectkit is excluded.

flags:
  --from=NAME          current name, default: the name in project()
  --description=TEXT   replace DESCRIPTION in CMakeLists.txt and the recipe
  --url=URL            replace url in the recipe
  --version=X.Y.Z      replace VERSION in CMakeLists.txt
  --dry-run            list what would change, touch nothing
  --yes, -y            do not ask for confirmation
  --force              run even when the git tree is dirty
  --help, -h           this message

A name must match [a-z][a-z0-9_]*: the sample sources use it as a C++
namespace, so hyphens would not compile.
USAGE
}

NEW_NAME=""
OLD_NAME=""
DESCRIPTION=""
URL=""
VERSION=""
DRY_RUN=0
ASSUME_YES=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from=*)        OLD_NAME="${1#--from=}"; shift ;;
    --description=*) DESCRIPTION="${1#--description=}"; shift ;;
    --url=*)         URL="${1#--url=}"; shift ;;
    --version=*)     VERSION="${1#--version=}"; shift ;;
    --dry-run)       DRY_RUN=1; shift ;;
    --yes|-y)        ASSUME_YES=1; shift ;;
    --force)         FORCE=1; shift ;;
    --help|-h)       usage; exit 0 ;;
    -*)              printf 'unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -z "$NEW_NAME" ]]; then
        NEW_NAME="$1"; shift
      else
        printf 'unexpected argument: %s\n\n' "$1" >&2; usage >&2; exit 2
      fi
      ;;
  esac
done

[[ -n "$NEW_NAME" ]] || { usage >&2; exit 2; }

if [[ ! "$NEW_NAME" =~ ^[a-z][a-z0-9_]*$ ]]; then
  pk_die "'${NEW_NAME}' must match [a-z][a-z0-9_]*, since the sample sources use it as a C++ namespace"
fi

if [[ -z "$OLD_NAME" ]]; then
  OLD_NAME="$(sed -n 's/^[[:space:]]*project[[:space:]]*([[:space:]]*\([A-Za-z0-9_.+-]\{1,\}\).*/\1/p' \
    "${PK_REPO_ROOT}/CMakeLists.txt" | head -n 1)"
fi

[[ -n "$OLD_NAME" ]] || pk_die "cannot determine the current name: pass --from=NAME"
[[ "$OLD_NAME" != "$NEW_NAME" ]] || pk_die "the project is already called '${NEW_NAME}'"

OLD_UPPER="$(printf '%s' "$OLD_NAME" | tr '[:lower:]' '[:upper:]')"
NEW_UPPER="$(printf '%s' "$NEW_NAME" | tr '[:lower:]' '[:upper:]')"
OLD_TITLE="$(printf '%s' "${OLD_NAME:0:1}" | tr '[:lower:]' '[:upper:]')${OLD_NAME:1}"
NEW_TITLE="$(printf '%s' "${NEW_NAME:0:1}" | tr '[:lower:]' '[:upper:]')${NEW_NAME:1}"

cd "$PK_REPO_ROOT" || pk_die "cannot enter ${PK_REPO_ROOT}"

if [[ "$FORCE" -eq 0 && "$DRY_RUN" -eq 0 ]] && git rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain)" ]]; then
    pk_die "the git tree is dirty; commit first so this is revertible, or pass --force"
  fi
fi

pk_paths_to_rename() {
  find . -depth -name "*${OLD_NAME}*" \
    ! -path "./.git/*" \
    ! -path "*/projectkit/*" \
    ! -path "*/build/*" \
    ! -path "*/stage/*" \
    ! -path "*/_install/*" \
    ! -path "*/.conan-cache/*" \
    -print
}

pk_files_to_edit() {
  grep -rIl --exclude-dir=.git --exclude-dir=build --exclude-dir=stage \
    --exclude-dir=_install --exclude-dir=projectkit --exclude-dir=.conan-cache \
    -e "$OLD_NAME" -e "$OLD_UPPER" -e "$OLD_TITLE" . 2>/dev/null
}

mapfile -t RENAMES < <(pk_paths_to_rename)
mapfile -t EDITS < <(pk_files_to_edit)

pk_note "project name: ${OLD_NAME} -> ${NEW_NAME}"
pk_note "identifiers:  ${OLD_UPPER} -> ${NEW_UPPER}, ${OLD_TITLE} -> ${NEW_TITLE}"
printf '\n%spaths to rename (%d)%s\n' "$PK_BOLD" "${#RENAMES[@]}" "$PK_RESET"
printf '  %s\n' "${RENAMES[@]}"
printf '\n%sfiles to rewrite (%d)%s\n' "$PK_BOLD" "${#EDITS[@]}" "$PK_RESET"
printf '  %s\n' "${EDITS[@]}"
printf '\n'

if [[ "$DRY_RUN" -eq 1 ]]; then
  pk_note "dry run, nothing changed"
  exit 0
fi

if [[ "$ASSUME_YES" -eq 0 ]]; then
  printf 'rename %s to %s? [y/N] ' "$OLD_NAME" "$NEW_NAME"
  read -r answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { pk_note "nothing changed"; exit 0; }
fi

for path in "${RENAMES[@]}"; do
  [[ -e "$path" ]] || continue
  directory="$(dirname "$path")"
  base="$(basename "$path")"
  new_base="${base//${OLD_NAME}/${NEW_NAME}}"
  new_base="${new_base//${OLD_UPPER}/${NEW_UPPER}}"
  new_base="${new_base//${OLD_TITLE}/${NEW_TITLE}}"
  [[ "$base" == "$new_base" ]] && continue

  if git rev-parse --git-dir >/dev/null 2>&1 && git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    git mv "$path" "${directory}/${new_base}" || pk_die "git mv failed: ${path}"
  else
    mv "$path" "${directory}/${new_base}" || pk_die "mv failed: ${path}"
  fi
done

if [[ "${#EDITS[@]}" -gt 0 ]]; then
  # Re-resolve, since the rename step moved some of these files.
  mapfile -t EDITS < <(pk_files_to_edit)
  printf '%s\n' "${EDITS[@]}" | while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    sed -i \
      -e "s/${OLD_UPPER}/${NEW_UPPER}/g" \
      -e "s/${OLD_TITLE}/${NEW_TITLE}/g" \
      -e "s/${OLD_NAME}/${NEW_NAME}/g" \
      "$file"
  done
fi

if [[ -n "$DESCRIPTION" ]]; then
  sed -i "s|\(DESCRIPTION[[:space:]]*\)\"[^\"]*\"|\1\"${DESCRIPTION}\"|" CMakeLists.txt
  [[ -f conanfile.py ]] && \
    sed -i "s|^\([[:space:]]*description[[:space:]]*=[[:space:]]*\)\".*\"|\1\"${DESCRIPTION}\"|" conanfile.py
fi

if [[ -n "$URL" && -f conanfile.py ]]; then
  sed -i "s|^\([[:space:]]*url[[:space:]]*=[[:space:]]*\)\".*\"|\1\"${URL}\"|" conanfile.py
fi

if [[ -n "$VERSION" ]]; then
  if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    pk_die "--version must be X.Y.Z, the recipe parses that shape"
  fi
  sed -i "s|\(VERSION[[:space:]]*\)[0-9]\{1,\}\.[0-9]\{1,\}\.[0-9]\{1,\}|\1${VERSION}|" CMakeLists.txt
fi

printf '\n'
remaining="$(grep -rIl --exclude-dir=.git --exclude-dir=build --exclude-dir=projectkit \
  -i "$OLD_NAME" . 2>/dev/null)"

if [[ -n "$remaining" ]]; then
  pk_warn "still mentioning '${OLD_NAME}':"
  printf '  %s\n' $remaining
else
  printf '%sno occurrences of %s remain outside the kit%s\n' \
    "$PK_GREEN" "$OLD_NAME" "$PK_RESET"
fi

kit_hits="$(grep -rIl -i "$OLD_NAME" cmake/projectkit \
  --include='*.cmake' --include='*.in' --include='*.sh' --include='*.py' \
  --exclude-dir=build 2>/dev/null)"
if [[ -n "$kit_hits" ]]; then
  pk_warn "the kit mentions '${OLD_NAME}', which is a bug in the kit:"
  printf '  %s\n' $kit_hits
fi

cat <<NEXT

next:
  git diff --stat
  ./scripts/package.sh reference
  ./scripts/package.sh install --build_type=Debug
  cmake --preset native-debug
  ./scripts/verify.sh run --build_type=Debug

then review by hand:
  CMakeLists.txt   DESCRIPTION and VERSION
  conanfile.py     description, url, package_info libs
  README.md        still describes the template
NEXT
