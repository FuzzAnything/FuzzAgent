<div align="center">
## 🤖 FuzzAgent

An autonomous fuzzing test agent for real-world projects.

![MIT License](https://img.shields.io/badge/License-MIT-blue)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue)


</div>

## For Users

Fuzzagent is an automated system for the full workflow of library fuzzing. You only need provided your source code as the inputs. We highly recommend everyone to have a try of FuzzAgent.


## 🧑‍💻 Usage
The project is built and tested on Ubuntu 24.04.1 LTS with Docker.

### 1. Build from Docker:
You can follow the [official guide](https://docs.docker.com/engine/install/ubuntu/) to install Docker on your system. 

- Build an image from Dockerfile:
```bash
cd FuzzAgent
docker buildx build -t fuzzagent -f docker/Dockerfile .
```

### 2. Configure the LLM
Copy `.env_template` to `.env` and fill in the OpenAI-compatible endpoint, API key, and model name. A GitHub token is optional; create one at [github.com/settings/tokens](https://github.com/settings/tokens) if you want to enable GitHub search.


### 3. Start a paper benchmark target
Choose one of the 20 libraries evaluated in the paper. The launcher clones it into `.cache/targets/<target>`, stores results in `output/<target>`, and starts its container. You do not need to set source or output paths.

```bash
./benchmark/run.sh cjson
```

Available targets: `cjson`, `libmagic`, `re2`, `pugixml`, `zlib`, `c-ares`, `liblouis`, `libpng`, `libpcap`, `libtiff`, `lcms`, `tinygltf`, `libjpeg-turbo`, `curl`, `libvpx`, `sqlite`, `libaom`, `openssl`, `protobuf`, and `opencv`.

The container is named `fuzzagent-<target>`. Logs and fuzzing artifacts are stored under `output/<target>`.
