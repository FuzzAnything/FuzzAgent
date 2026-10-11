#/usr/bin/sh
set -eux

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find all /bin directories and copy their contents to /usr/local/bin
find "$SCRIPT_DIR" -type d -name "bin" | while read bin_dir; do
    if [ -d "$bin_dir" ]; then
        echo "Copying contents from $bin_dir to /usr/local/bin"
        cp -r "$bin_dir"/* /usr/local/bin/ 2>/dev/null || true
    fi
done

# copy utils/bin to /usr/local/bin
rm -f /usr/local/bin/project_utils.py
cp  "/root/FuzzAgent/src/tools/utils/bin/project_utils.py" /usr/local/bin/project_utils.py 2>/dev/null || true
cp "/src/" "/root/src/" -r 2>/dev/null || true