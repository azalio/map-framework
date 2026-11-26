set -eu
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
printf 'first\n' > "$dir/tag"
sh sign.sh "$dir/tag" "$dir"
printf 'second\n' > "$dir/tag"
test "$(cat "$dir/first.signed")" = first
test ! -e "$dir/second.signed"
