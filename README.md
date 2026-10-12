<div align="center">
## 🤖 FuzzAgent

An autonomous fuzzing test agent for real-world projects.

[![License: AGPL-3.0-only or Commercial](https://img.shields.io/badge/License-AGPL--3.0--only%20%2F%20Commercial-blue)](LICENSE)
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

#### Available targets

The 20 paper benchmark targets are listed alphabetically. Click a library name to visit its source repository, and use its target ID with `./benchmark/run.sh <target>`.

| Library | Focus | Target ID |
| :--- | :--- | :--- |
| [c-ares](https://github.com/c-ares/c-ares) | Asynchronous DNS resolution | `c-ares` |
| [cJSON](https://github.com/DaveGamble/cJSON) | JSON parsing and serialization | `cjson` |
| [curl](https://github.com/curl/curl) | Data transfer and network protocols | `curl` |
| [libaom](https://aomedia.googlesource.com/aom) | AV1 video encoding and decoding | `libaom` |
| [libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo) | JPEG encoding and decoding | `libjpeg-turbo` |
| [liblouis](https://github.com/liblouis/liblouis) | Braille translation | `liblouis` |
| [libmagic](https://github.com/file/file) | File type identification | `libmagic` |
| [libpcap](https://github.com/the-tcpdump-group/libpcap) | Network packet capture | `libpcap` |
| [libpng](https://github.com/pnggroup/libpng) | PNG encoding and decoding | `libpng` |
| [libtiff](https://github.com/libsdl-org/libtiff) | TIFF image processing | `libtiff` |
| [libvpx](https://chromium.googlesource.com/webm/libvpx) | VP8 and VP9 video encoding and decoding | `libvpx` |
| [Little CMS](https://github.com/mm2/Little-CMS) | Color management | `lcms` |
| [OpenCV](https://github.com/opencv/opencv) | Computer vision and image processing | `opencv` |
| [OpenSSL](https://github.com/openssl/openssl) | Cryptography and TLS | `openssl` |
| [Protocol Buffers](https://github.com/protocolbuffers/protobuf) | Structured data serialization | `protobuf` |
| [pugixml](https://github.com/zeux/pugixml) | XML parsing and processing | `pugixml` |
| [RE2](https://github.com/google/re2) | Regular expression matching | `re2` |
| [SQLite](https://github.com/sqlite/sqlite) | Embedded SQL database | `sqlite` |
| [TinyGLTF](https://github.com/syoyo/tinygltf) | glTF model loading and serialization | `tinygltf` |
| [zlib](https://github.com/madler/zlib) | Data compression | `zlib` |


## License

FuzzAgent is available under a dual-license model:

- **AGPL-3.0-only:** Free to use, modify, and distribute under the terms of the [GNU Affero General Public License v3](LICENSE), including for commercial purposes.
- **Commercial license:** Available by separate agreement with the copyright holders for use, modification, distribution, or deployment under alternative terms.

Companies may use FuzzAgent under the AGPL; a commercial license is an alternative for those who need different terms. Third-party components retain their respective licenses.

# Citation
```
@misc{lyu2026fuzzagentmultiagentevolutionarylibrary,
      title={FuzzAgent: Multi-Agent System for Evolutionary Library Fuzzing}, 
      author={Yunlong Lyu and Peng Chen and Fengyi Wu and Junzhe Yu and Kit Long Hon and Hao Chen},
      year={2026},
      eprint={2605.14431},
      archivePrefix={arXiv},
      primaryClass={cs.SE},
      url={https://arxiv.org/abs/2605.14431}, 
}
```
