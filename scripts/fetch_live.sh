#!/usr/bin/env bash
# Download a file from the live site into public/, for the nightly job:
#   scripts/fetch_live.sh data.json
# Tries the custom domain first, then the github.io address, so a night when the
# domain's DNS isn't answering doesn't lose the previous data (B6b). Fails, and
# leaves no partial file, when neither has it.
set -u
file="$1"
mkdir -p public
for base in https://sydneycinema.com https://harveylrc.github.io/sydney-cine; do
  if curl -fsSL --max-time 60 "$base/$file" -o "public/$file"; then
    echo "Downloaded $file from $base"
    exit 0
  fi
done
rm -f "public/$file"
exit 1
