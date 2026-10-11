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
cd FuzzAgent-Core
docker buildx build -t fuzzagent -f docker/Dockerfile .
```

### 2. Setting
Copy the file `.env_template` to the file `.env` and then complete the following values:
- llm values
- project-specific values

For example:
```
## llm values
export OPENAI_BASE_URL=https://api.deepseek.com
export OPENAI_API_KEY=sk-xxxx
export OPENAI_MODEL=deepseek-v4-pro

## project-specific values
export SRC_DIR=/path/to/source
export REPO_BASE_NAME=project_name # e.g., openssl
export RAW_OUTPUT_DIR=/tmp/fuzzagent_output

# Feature values
export GITHUB_TOKEN="xxx"
```


### 3. Start:
To start a scan task, follow:

```
$ source .env
$ export FUZZAGENT_DIR=$(pwd)
$ docker compose -f controller/docker_template.yml up -d
$ docker container ls
```
You should observe a docker container named `fuzzagent-test` is running.

Also, you can check your output directory (e.g., `/tmp/fuzzagent_output`). The log file is located at: `.cache/logs/*.log`


### 4. Export Full Code Coverage
After 24h fuzzing on the target library, you can run the following commands to export the full code coverage:

```
$ source .env
$ export FUZZAGENT_DIR=$(pwd)
$ export COMMAND='bash /root/FuzzAgent/src/tools/copy_tools.sh && python3 -m introspector'
$ docker compose -f controller/docker_template.yml up
```

The exported code coverage will be saved in the `.cache/coverage` directory under your output directory.

### 5. Attach:
For debugging purpose, you can attach in to the docker container:
```
$ docker exec -it fuzzagent-test /bin/bash
```


-----
Now enjoy it.

## Developer Guide

### Code Formatter
There are the code formatters provided in the Vscode Plugin Market.
[Vscode Code Formatter](https://code.visualstudio.com/docs/python/formatting#_choose-a-formatter)

We should choose the [Black formatter](https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter) as the code formatter, and format your code after your changes every time.

### Git Commits
Break your changes into tiny and individual commits (or branches).

https://www.kernel.org/doc/html/v4.14/process/howto.html#break-up-your-changes

### Code Linter
We use [Pylint](https://marketplace.visualstudio.com/items?itemName=ms-python.pylint) to ensure the code quality.

Please install and enbale it. Make sure there is no low-level faults in your code!
e code quality.

Please install and enbale it. Make sure there is no low-level faults in your code!
