set -eu
digest=$(cat "$1")
printf '%s\n' "$digest" > "$2/$digest.signed"
