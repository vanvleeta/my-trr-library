#!/bin/bash
# TRR number assignment script. Run from the root of the repository.
#
# Usage: tools/trr-assign.sh [OldTRRNumber] [NewTRRNumber]
#
#   OldTRRNumber  optional, defaults to trr0000 (the placeholder used by all
#                 new reports, in every repository regardless of prefix)
#   NewTRRNumber  optional, defaults to the next available number using this
#                 repository's configured ID prefix
#
# The script replaces OldTRRNumber inside files and in filenames within the
# 'reports/OldTRRNumber' folder, then renames the folder itself.
#
# Requires python3, which the indexer already depends on.

set -u

CONFIG="local/config.json"
INDEX="index.json"
PLACEHOLDER="trr0000"

if [ ! -f "$CONFIG" ]; then
  printf "Error: %s not found. Run this script from the repository root.\n" "$CONFIG"
  exit 1
fi

# Read and sanity check this repository's ID prefix.
prefix=$(python3 -c "
import json, re, sys
try:
    config = json.load(open('$CONFIG'))
except json.JSONDecodeError as e:
    sys.exit(f'$CONFIG is not valid JSON: {e}')
prefix = config.get('id_prefix')
if not prefix:
    sys.exit(\"$CONFIG is missing 'id_prefix'.\")
if prefix == 'XXXX':
    sys.exit(\"'id_prefix' is still the template placeholder 'XXXX'. Set it in $CONFIG.\")
if not re.match(r'^[A-Z][A-Z0-9]{1,7}\$', prefix):
    sys.exit(f\"'id_prefix' value '{prefix}' is invalid.\")
print(prefix)
") || { printf "Configuration error: %s\n" "$prefix"; exit 1; }

prefix_lower="${prefix,,}"

# Determine the old number.
if [ $# -ge 1 ] && [ -n "$1" ]; then
  oldnum_upper="${1^^}"
  oldnum_lower="${1,,}"
else
  oldnum_upper="${PLACEHOLDER^^}"
  oldnum_lower="$PLACEHOLDER"
fi

# Determine the new number.
if [ $# -ge 2 ] && [ -n "$2" ]; then
  newnum_upper="${2^^}"
  newnum_lower="${2,,}"
else
  # Scan every index entry for the highest assigned number. Reading the last
  # entry is not safe: merge order does not keep the index sorted, so the tail
  # can hand out a number that is already in use.
  lastnum=$(python3 -c "
import json, re
try:
    index = json.load(open('$INDEX'))
except (FileNotFoundError, json.JSONDecodeError):
    index = []
pattern = re.compile(r'^$prefix(\d+)\$', re.IGNORECASE)
numbers = [int(m.group(1), 10) for m in
           (pattern.match(entry.get('id', '')) for entry in index) if m]
print(max(numbers) if numbers else 0)
")

  printf "Last number assigned is: %s\n" "$lastnum"
  newnum=$(printf "%s%04d" "$prefix" $((lastnum + 1)))
  printf "Next available number is: %s\n" "$newnum"
  newnum_upper="${newnum^^}"
  newnum_lower="${newnum,,}"
fi

# Verify both numbers before proceeding. The old number may be the universal
# placeholder or an already-assigned ID; the new number must use this
# repository's prefix.
old_pattern="^(${PLACEHOLDER^^}|${prefix}[0-9]{4})\$"
new_pattern="^${prefix}[0-9]{4}\$"

if [[ ! $oldnum_upper =~ $old_pattern ]]; then
  printf "Error: '%s' is not a valid TRR number for this repository.\n" "$oldnum_upper"
  exit 1
fi

if [[ ! $newnum_upper =~ $new_pattern ]]; then
  printf "Error: '%s' does not match this repository's prefix '%s'.\n" "$newnum_upper" "$prefix"
  exit 1
fi

if [ ! -d "./reports/$oldnum_lower" ]; then
  printf "Error: reports/%s does not exist.\n" "$oldnum_lower"
  exit 1
fi

# Without this check a rename onto an existing folder would nest the report
# inside it rather than failing.
if [ -e "./reports/$newnum_lower" ]; then
  printf "Error: reports/%s already exists. %s is already assigned.\n" \
    "$newnum_lower" "$newnum_upper"
  exit 1
fi

printf "TRR Number assignment script - assigning %s to %s.\n" "$oldnum_upper" "$newnum_upper"

# Replace the uppercase string in the README.md files
find ./reports/$oldnum_lower -name 'README.md' -exec sed -i "s/$oldnum_upper/$newnum_upper/g" {} +
# Replace the lowercase string in the README.md files
find ./reports/$oldnum_lower -name 'README.md' -exec sed -i "s/$oldnum_lower/$newnum_lower/g" {} +
# Rename any file whose name carries the old number (filenames are lowercase)
find ./reports/$oldnum_lower -mindepth 1 -depth -name "*$oldnum_lower*" | while read -r path; do
  dir=$(dirname "$path")
  base=$(basename "$path")
  mv "$path" "$dir/${base//$oldnum_lower/$newnum_lower}"
done
# Finally, rename the folder itself
mv ./reports/$oldnum_lower ./reports/$newnum_lower

printf "Reassignment complete.\n"
