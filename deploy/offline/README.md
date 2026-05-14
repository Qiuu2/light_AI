# AI Speaker 麒麟 V10 离线部署手册

本文档说明 AI Speaker 在 `Kylin V10 x86_64` 环境下的离线打包、安装、验证与运维方式。

## 一、部署目标

本离线包只包含 AI Speaker 自身运行所需内容，不再要求以下系统包目录：

- `docker/`
- `firefox/`
- `heartbeat/`

最终目标是：

- 在 `Linux x86_64` 打包机上生成离线安装包
- 把离线包整体拷到麒麟 V10 机器
- 执行安装脚本后自动完成部署并启动后台
- 用户通过浏览器访问 `http://设备IP:5018/` 打开 AI 页面

## 二、运行架构

- 后端服务：`backend.api_public:app`
- 启动方式：`systemd`
- 服务端口：`5018`
- Python 运行时：`Miniconda base`
- 前端资源：支持仓库根目录 `dist/` 或 `web/dist`
- 浏览器访问地址：`http://设备IP:5018/`

说明：

- 当前离线方案不需要 `nginx`
- 当前离线方案不需要 Docker
- 当前离线方案不要求在目标机现场构建前端
- 前端生产环境直接请求根路径 API，不再依赖 `/prod-api`

## 三、打包机要求

离线包必须在 `Linux x86_64` 打包机上生成，不能在 Windows 上直接执行最终打包。

原因：

- `wheelhouse/` 中的 Python 依赖包来自打包机本机环境
- Windows 打出的依赖包不能直接在麒麟 Linux 上安装

## 四、打包前准备

在 Linux 打包机上，项目目录至少应包含以下内容：

- `backend/`
- `src/`
- `deploy/`
- `models/`
- `python/`
- `scripts/`
- 根目录 `dist/` 或 `web/dist/`
- `kylininstall.sh`
- `kylininstall-ai-speaker.sh`
- `requirements.txt`

说明：

- 根目录 `main.py` 不属于离线部署硬依赖
- 根目录 `README.md` 不属于离线部署硬依赖
- 正式交付文档来自 `deploy/offline/README.md`

并确认：

- `models/joint_rbt3/` 模型文件完整
- `python/` 下有可用的 Miniconda 安装器，或者准备通过 `--python-installer` 指定
- 前端构建产物存在于根目录 `dist/` 或 `web/dist/`

## 五、打包命令

### 方式 1：复用现有前端构建产物

如果 Linux 打包机上已经有可用的根目录 `dist/` 或 `web/dist/`，推荐使用：

```bash
cd /path/to/AI_Speaker_Project
python scripts/build_kylin_offline_bundle.py --skip-web-build
```

打包机历史命令记录显示，实际执行时使用过如下 Conda 环境：

```bash
conda activate ai-speaker-py39
python scripts/build_kylin_offline_bundle.py --skip-web-build
```

如需复现既有打包流程，建议先激活 `ai-speaker-py39`，再执行打包命令。

脚本会按以下顺序查找前端产物：

1. 仓库根目录 `dist/`
2. `web/dist/`

### 方式 2：在 Linux 打包机重新构建前端

如果希望在打包时自动构建前端：

```bash
cd /path/to/AI_Speaker_Project
python scripts/build_kylin_offline_bundle.py
```

该命令会在 `web/` 目录执行前端构建，然后按同样的路径规则读取构建产物。

### 方式 3：显式指定 Miniconda 安装器

```bash
cd /path/to/AI_Speaker_Project
python scripts/build_kylin_offline_bundle.py \
  --python-installer /path/to/Miniconda3-py39_24.11.1-0-Linux-x86_64.sh \
  --skip-web-build
```

### 默认输出目录

```bash
deploy/out/kylin-v10-x86_64/
```

## CPU-Only Bundle Defaults

The offline bundle now uses a dedicated CPU-only runtime requirements file:

- `deploy/offline/requirements.runtime.cpu.txt`

This file is copied into the final bundle as:

- `app/requirements.txt`

The default runtime bundle pins these CPU-only packages:

- `torch==2.8.0+cpu`
- `transformers==4.57.3`
- `datasets==4.4.2`
- `pytorch-crf==0.7.2`

The build script also reuses a persistent wheelhouse cache by default:

- `deploy/cache/wheelhouse/linux-x86_64-py39-cpu/`

On the first build, the cache is populated. Later builds reuse it instead of
re-downloading every wheel.

### Recommended Commands

Reuse an existing frontend build and reuse the cached wheelhouse:

```bash
cd /path/to/AI_Speaker_Project
python scripts/build_kylin_offline_bundle.py --skip-web-build
```

Force a fresh wheelhouse download into the persistent cache:

```bash
cd /path/to/AI_Speaker_Project
python scripts/build_kylin_offline_bundle.py --skip-web-build --refresh-wheelhouse
```

Use a custom wheelhouse cache directory:

```bash
cd /path/to/AI_Speaker_Project
python scripts/build_kylin_offline_bundle.py \
  --skip-web-build \
  --wheelhouse-cache-dir /path/to/wheelhouse-cache
```

## Model Packaging Note

The offline bundle must include the full repository-level `models/` directory,
not only `models/joint_rbt3/`.

At minimum, verify these files exist in the final bundle:

- `models/config.json`
- `models/pytorch_model.bin`
- `models/tokenizer.json`
- `models/tokenizer_config.json`
- `models/vocab.txt`
- `models/joint_rbt3/joint_model.pt`

This is required because runtime startup still loads the base encoder from the
repository-level `models/` directory. If the bundle ships only
`models/joint_rbt3/`, the service will fail during startup with
`Unrecognized model in models`.

The wheelhouse must also contain the correct CRF dependency for runtime:

- required: `pytorch-crf==0.7.2`
- forbidden: `TorchCRF` / `torchcrf>=1.1`
- required: CPU-only `torch==2.8.0+cpu`

If the bundle carries the wrong CRF package, the service may fail at startup
with errors around `batch_first` or `crf.*` state dict loading.
If the bundle carries a CUDA-enabled PyTorch wheel, the package will be larger
than necessary and may pull GPU-only dependencies into a CPU deployment.

## 六、打包产物目录结构

打包完成后，离线介质目录应类似如下：

```text
deploy/out/kylin-v10-x86_64/
+-- kylininstall.sh
+-- kylininstall-ai-speaker.sh
+-- python/
+-- wheelhouse/
+-- app/
+-- models/
+-- runtime-data/
+-- web-dist/
+-- systemd/
+-- docs/
+-- manifest.json
+-- checksums.txt
```

说明：

- `kylininstall.sh`：兼容入口脚本，会直接转调 `kylininstall-ai-speaker.sh`
- `kylininstall-ai-speaker.sh`：正式离线安装脚本
- `python/`：Miniconda 离线安装器
- `wheelhouse/`：Python 离线依赖包
- `app/`：项目运行代码
- `models/`：模型文件
- `runtime-data/`：基础配置和静态数据
- `web-dist/`：前端构建产物
- `systemd/ai-speaker.service`：systemd 服务文件
- `manifest.json` / `checksums.txt`：文件清单与校验信息

## 七、运行数据约定

`runtime-data/` 只应包含基础配置和静态数据，不应包含运行状态文件。

### 可以随离线包交付的基础数据

- `all_audio.json`
- `all_loc.json`
- `all_task.json`
- `assistant_settings.json`
- `broadcast_schedules.json`
- `calendar_holidays_cn.json`
- `license_codes.json`
- `schedule_template`
- `schedule_templates/`
- `task_overrides.json`
- `templates.json`

### 不应随离线包交付的运行状态文件

- `license_state.json`
- `assistant_command_logs.json`
- `remote_sync_meta.json`

这些状态文件会在安装时由目标机自动初始化。

## 八、现场安装步骤

假设你已经把 `deploy/out/kylin-v10-x86_64/` 整个目录拷到目标麒麟机器中。

进入离线目录：

```bash
cd /path/to/kylin-v10-x86_64
```

推荐直接执行正式安装脚本：

```bash
bash kylininstall-ai-speaker.sh
```

如果现场人员习惯使用旧入口，也可以执行：

```bash
bash kylininstall.sh
```

它会自动转调 `kylininstall-ai-speaker.sh`。

安装脚本会自动完成：

- 校验目标机是 `Kylin V10 x86_64`
- 安装 Miniconda 到 `/opt/ai-speaker/miniconda3`
- 使用 Miniconda base 安装 Python 依赖
- 部署项目代码到 `/opt/ai-speaker/app`
- 部署模型文件
- 部署基础数据
- 初始化运行状态文件
- 部署前端静态资源
- 安装并启动 `systemd` 服务

## 九、安装完成后的验证命令

### 1. 查看服务状态

```bash
sudo systemctl status ai-speaker
```

预期结果：

- 出现 `active (running)`

### 2. 验证后端接口

```bash
curl http://127.0.0.1:5018/license/status
```

预期结果：

- 返回 JSON
- 接口正常响应

### 3. 查看最近日志

```bash
sudo journalctl -u ai-speaker -n 100
```

### 4. 实时查看日志

```bash
sudo journalctl -u ai-speaker -f
```

### 5. 浏览器访问

在浏览器中访问：

```text
http://设备IP:5018/
```

预期结果：

- 前端页面可以打开
- 页面可以正常调用后端接口
- 页面请求不再走 `/prod-api`

## 十、常用运维命令

启动服务：

```bash
sudo systemctl start ai-speaker
```

停止服务：

```bash
sudo systemctl stop ai-speaker
```

重启服务：

```bash
sudo systemctl restart ai-speaker
```

查看状态：

```bash
sudo systemctl status ai-speaker
```

查看最近 100 行日志：

```bash
sudo journalctl -u ai-speaker -n 100
```

实时查看日志：

```bash
sudo journalctl -u ai-speaker -f
```

检查是否开机自启：

```bash
sudo systemctl is-enabled ai-speaker
```

## 十一、交付前人工检查项

在把离线介质交给现场之前，至少检查以下内容：

1. `wheelhouse/` 已生成且不为空
2. `python/` 下存在 Miniconda 安装器
3. `models/joint_rbt3/` 下存在 `joint_model.pt`
4. `web-dist/index.html` 存在
5. `systemd/ai-speaker.service` 存在
6. `runtime-data/` 中不包含：
   - `license_state.json`
   - `assistant_command_logs.json`
   - `remote_sync_meta.json`
7. `manifest.json` 和 `checksums.txt` 已生成

## 十二、常见问题

### 1. 为什么必须在 Linux x86_64 上打包？

因为 Python 离线依赖包和平台相关。Windows 上打出来的包，麒麟 Linux 上不能直接安装。

### 2. 为什么不再创建独立 conda 环境？

因为离线环境中 `conda create` 容易因为 channel 元数据或缺包问题失败。直接使用 Miniconda base 更稳。

### 3. 为什么不再要求 docker/firefox/heartbeat？

因为它们不属于 AI Speaker 自身运行的硬依赖。把它们从离线包中剥离后，打包与现场安装更简单、更稳。

### 4. 为什么不再要求根目录 `main.py`？

根目录 `main.py` 只是 CLI 调试入口，不是离线部署服务的运行入口。离线安装真正运行的是 `backend.api_public:app`。

### 5. 为什么不再要求根目录 `README.md`？

根目录 `README.md` 只是项目说明文档，不属于离线部署硬依赖。现场安装所需的正式说明文档由 `deploy/offline/README.md` 提供。

### 6. 为什么现在支持根目录 `dist/`？

因为当前实际打包机目录中，前端产物已经在根目录 `dist/`。脚本兼容根目录 `dist/` 和 `web/dist/` 后，现场不需要再手工挪目录。

### 7. 如果打包时报缺少 `main.py` 或根目录 `README.md` 怎么看？

优先把这类错误视为“打包脚本仍然要求了非运行必需文件”。正式方案应修正脚本，而不是在 Linux 打包机上长期手工补这些文件。手工补文件只能作为临时绕行方式。
## Runtime Hardening Addendum

- Keep the deployment in single-process mode. Do not enable multiple `uvicorn`
  workers for this build while pending actions, session state, and runtime
  caches are still process-local.
- The service now exposes:
  - `GET /healthz` for liveness
  - `GET /readyz` for readiness and degraded remote-sync state
  - `GET /ops/status` for runtime diagnostics such as uptime, RSS memory, and
    last remote sync result
- The `systemd` unit reads an optional environment file:

```bash
/etc/ai-speaker/ai-speaker.env
```

- Recommended runtime overrides:

```bash
REMOTE_BASE_URL=
REMOTE_TIMEOUT=15
REMOTE_AUTO_SYNC_SECONDS=180
DEBUG_REMOTE=0
CORS_ALLOW_ORIGINS=
```

Leave `REMOTE_BASE_URL` blank when the deployment address varies by site. The
login bootstrap flow can suggest candidate addresses and persist the selected
value into runtime settings.

- Verification after install:

```bash
curl http://127.0.0.1:5018/healthz
curl http://127.0.0.1:5018/readyz
curl http://127.0.0.1:5018/ops/status
```

- If `/readyz` returns `503`, the instance is not ready for handoff. If it
  returns `200` with `"degraded": true`, the backend is alive but remote sync
  needs investigation before formal acceptance.

## Delivery Verification Semantics

Treat bundle verification and runtime verification as two separate steps.

1. Verify bundle structure only:

```bash
python docs/verify_rc_candidate.py --bundle-dir . --skip-http-probe
```

Expected result:

- output includes `bundle structure verified`
- `manifest.json` and `checksums.txt` exist
- `wheelhouse/` is not empty
- `models/` contains the required model payload
- `runtime-data/` does not ship target-generated state such as
  `license_state.json`, `assistant_command_logs.json`, or `remote_sync_meta.json`

2. Verify runtime endpoints after install:

```bash
python docs/verify_rc_candidate.py --bundle-dir . --base-url http://127.0.0.1:5018
```

Expected result:

- output includes `runtime endpoints verified`
- `/healthz` returns `200`
- `/ops/status` returns `200`
- `/readyz` returns `200` for a handoff-ready system, or `503` when the service
  is alive but not yet ready

## CORS Override

The delivered service no longer defaults to `allow_origins=["*"]`. Use
`CORS_ALLOW_ORIGINS` only when a separate browser origin must call the API.
Leave it empty for the default same-origin deployment.
