Background command "cd /home/user/git/luckydonald/game_collections
git fsck --no-reflog --unreachable --full 2>/dev/null | awk '{print $3}' > /tmp/dangling.txt
wc -l /tmp/dangling.txt
for h in $(cat /tmp/dangling.txt); do
  type=$(git cat-file -t "$h" 2>/dev/null)
  if [ "$type" = "blob" ]; then
    if git cat-file -p "$h" 2>/dev/null | grep -q "package_split_games"; then
      echo "FOUND in blob $h"
    fi
  fi
done" completed (exit code 0)