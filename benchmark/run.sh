#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"

declare -A TARGET_REPOS=(
    [cjson]=https://github.com/DaveGamble/cJSON.git
    [libmagic]=https://github.com/file/file.git
    [re2]=https://github.com/google/re2.git
    [pugixml]=https://github.com/zeux/pugixml.git
    [zlib]=https://github.com/madler/zlib.git
    [c-ares]=https://github.com/c-ares/c-ares.git
    [liblouis]=https://github.com/liblouis/liblouis.git
    [libpng]=https://github.com/pnggroup/libpng.git
    [libpcap]=https://github.com/the-tcpdump-group/libpcap.git
    [libtiff]=https://github.com/libsdl-org/libtiff.git
    [lcms]=https://github.com/mm2/Little-CMS.git
    [tinygltf]=https://github.com/syoyo/tinygltf.git
    [libjpeg-turbo]=https://github.com/libjpeg-turbo/libjpeg-turbo.git
    [curl]=https://github.com/curl/curl.git
    [libvpx]=https://chromium.googlesource.com/webm/libvpx
    [sqlite]=https://github.com/sqlite/sqlite.git
    [libaom]=https://aomedia.googlesource.com/aom
    [openssl]=https://github.com/openssl/openssl.git
    [protobuf]=https://github.com/protocolbuffers/protobuf.git
    [opencv]=https://github.com/opencv/opencv.git
)

if [[ -z "$TARGET" || -z "${TARGET_REPOS[$TARGET]:-}" ]]; then
    printf 'Usage: %s <target>\n\nAvailable targets:\n' "$0" >&2
    printf '  %s\n' "${!TARGET_REPOS[@]}" | sort >&2
    exit 2
fi

ENV_FILE="$ROOT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    printf 'Missing %s. Copy .env_template to .env and configure the LLM endpoint.\n' "$ENV_FILE" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
for name in OPENAI_BASE_URL OPENAI_API_KEY OPENAI_MODEL; do
    if [[ -z "${!name:-}" ]]; then
        printf 'Set %s in %s.\n' "$name" "$ENV_FILE" >&2
        exit 1
    fi
done

TARGET_DIR="$ROOT_DIR/.cache/targets/$TARGET"
mkdir -p "$(dirname "$TARGET_DIR")" "$ROOT_DIR/output"
if [[ ! -d "$TARGET_DIR/.git" ]]; then
    if [[ -e "$TARGET_DIR" ]]; then
        printf 'Target path exists but is not a Git checkout: %s\n' "$TARGET_DIR" >&2
        exit 1
    fi
    git clone --depth 1 "${TARGET_REPOS[$TARGET]}" "$TARGET_DIR"
fi

export CONTAINER_NAME="fuzzagent-$TARGET"
export FUZZING_DURATION="${FUZZING_DURATION:-24h}"
# The container runs main.py for this duration, then exports full code coverage.
export COMMAND='bash /root/FuzzAgent/benchmark/run_benchmark.sh'
export WRITE_MODE=rw
export FUZZING_ENGINE=afl++
export FUZZAGENT_AUTO_CLEAN=1
export FUZZAGENT_DIR="$ROOT_DIR"
export SRC_DIR="$TARGET_DIR"
export REPO_BASE_NAME="$TARGET"
export RAW_OUTPUT_DIR="$ROOT_DIR/output/$TARGET"

exec docker compose -p "$CONTAINER_NAME" -f "$ROOT_DIR/controller/docker_template.yml" up -d
