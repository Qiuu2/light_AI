# AI Speaker Project

AI Speaker Project is a campus broadcast assistant that combines NLU, scheduling, remote device control, and a Vue-based admin UI. This README is intentionally short and focused on day-to-day development. For deeper project conventions and intent taxonomy, see `AGENTS.md`.

## Quick Start

### Backend

```bash
pip install -r requirements.txt
python -m uvicorn backend.api_public:app --reload --port 5012
```

Alternative module entry:

```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd web
npm install
npm run dev
```

### Training and Evaluation

```bash
python src/preprocessor.py
python src/trainer.py
python src/evaluate.py
```

## Common Tests

```bash
pytest backend/tests/
python scripts/test_engine_smoke.py
```

Frontend unit tests:

```bash
cd web
npm run test:unit
```

## Directory Guide

| Path | Purpose |
| --- | --- |
| `src/` | Joint RBT3 NLU training, inference, and dialogue management |
| `backend/` | FastAPI service, execution logic, defaults, and tests |
| `web/` | Vue 2 + Element UI frontend |
| `scripts/` | Developer utility scripts and smoke checks |
| `deploy/` | Windows installer tooling and optional systemd service files |
| `models/` | Local model directory, ignored by default |
| `data/` | Local training or reference data kept outside normal version control flow in this workspace |
| `backend/default_data/` | Versioned default static data |
| `backend/data/` | Runtime data directory, ignored by default |

## Dev Entry Points and Boundaries

- Daily development happens in `backend/`, `src/`, `web/`, and `scripts/`.
- Files under `deploy/` support Windows packaging and optional service deployment. They are not the source of truth for application behavior.
- Root-level archives, old notes, and SDK reference files are auxiliary materials. Keep them out of routine debugging unless they are directly relevant.

## Workspace Hygiene

- Source directories: `src/`, `backend/`, `web/src/`
- Versioned defaults: `backend/default_data/`
- Local runtime data: `backend/data/`
- Local cache and temp outputs: `.pytest_cache/`, `.pytest_tmp_*`, `tmp*`, `bundlecheck_*`, `__pycache__/`, `backend/tests/license-tests-*`
- Local dataset area: `data/`
- Local dataset cache: `hf_cache/`, `data/hf_cache/`

Use the cleanup helper below to preview or remove common temporary outputs:

```bash
python scripts/cleanup_workspace.py
python scripts/cleanup_workspace.py --apply
```

## Prerequisites

- Python 3.9+ recommended, ideally 3.10
- Node.js for the frontend toolchain
- Model files prepared under `models/joint_rbt3/`
- Remote API environment variables configured through the Windows login/bootstrap flow or the example files in `deploy/systemd/`

## Further Reading

- Project guide: `AGENTS.md`
- Windows installer: `deploy/windows/README.md`
- systemd deployment: `deploy/systemd/README.md`

## AI 助手当前能力

精简后的 AI 助手只 dispatch 4 个意图，其他训练标签（共 31 个）仍可被模型识别但不再触发动作。

| 用户话术示例 | 模型意图 | 走的 handler | 远端调用 |
|---|---|---|---|
| 「播放大课间任务」 | `play_task` | play_task | `POST /action/taskstart` |
| 「停止午休铃任务」 | `stop_task` | stop_task | `POST /action/taskstop` |
| 「给操场播放国歌」 | `play_media` | play_media（带媒体分支） | `POST /action/executetmptask` 含 `media` |
| 「打开 1 号分区」「打开功放电源」「打开 1 区功放」 | `enable_terminal`（高置信度） | play_media（zone-only 分支） | `POST /action/executetmptask` 不含 `media`，只发 `area0-7` |
| 「关闭 1 号分区」「停止所有临时播放」 | `disable_terminal` / `stop_media` | stop_media | `POST /action/stoptmptask` |

实现要点：
- Dispatch 注册表在 `backend/assistant/dispatch.py`，6 个意图入口（4 个核心 + 2 个 alias）：
  - `play_task` / `stop_task` — 命名任务的播放/停止
  - `play_media` — 临时任务（带或不带媒体）
  - `stop_media` — 停止临时任务
  - `enable_terminal` → 复用 `apply_play_media_intent`（实测模型把"打开 X"识别成 enable_terminal，置信度 0.9999+）
  - `disable_terminal` → 复用 `apply_stop_media_intent`
- `_apply_play_media_intent` (`backend/api_public.py`) 将 `media_name` slot 改为可选；缺失时走 `_apply_zone_only_temp_task` 分支（仅下发 `area0-7`）。
- 文本里包含「功放」/「外控」时自动置 `area6=1` / `area7=1`，避免依赖 slot 抽取。
- `_resolve_zone_index` 支持纯数字 zone 值（slot 经常给出 "1" 而不是 "分区1"）+ 中文数字 + 剥词。
- `_overlay_all_zones_keywords` 支持三种多分区表达形式：
  - 全开：「全部分区」「所有分区」「全场」「全开」
  - 范围：「1 到 6 号分区」「一到六分区」「2 号到 5 号」
  - 枚举：「1, 3, 5 号分区」「1 号和 3 号分区」「一、二、三号分区」
- 不重训模型；其他 25 个训练标签仍可被模型识别但不再触发 action。
- 前端 `AiAssistantFloat.vue` 同步精简：移除"学校类型 + 季节"设置卡片，placeholder 与帮助文案只保留 4 类示例。
- **任务名远端 fallback**：`play_task` / `stop_task` 在本地 `broadcast_schedules` 缓存里找不到 task 时，自动调远端 `gettaskinfo`（只返回当前启用方案的任务，匹配业务"播放/停止已激活方案里的任务"的预期）做精确 → 标准化 → fuzzy 三层匹配。见 `_remote_find_task_id_by_name`。
  - 阈值 0.95：≥ 0.95（含 exact/normalized）直接执行；0.7 ≤ score < 0.95 视为低置信度，返回提示并建议用户用完整任务名重说，**不自动执行**，避免误开/误停。
  - 自动过滤 `enable=0` 的任务，不会触发被禁用的条目。
  - 单次 HTTP 调用，受 `LIGHT_REMOTE_TIMEOUT` 限制（默认 15s）。
  - 失败 / 数据异常时通过 `LOGGER.warning` 记录原始返回，方便排错。

## Known Issues

### 作息任务 `modifytask` / `addtask` 不接受分组 ID（`1_` 前缀）

**现象**：在「作息管理 → 编辑任务」弹窗里，"终端/分组"下拉框可以选**分组**（label 例如 "123"，前端 value 为 `1_69`）或**未分组的独立终端**（value 例如 `2_446`）。选了分组提交后，远端 `/action/modifytask` 返回 `ok`，但立刻调 `/action/gettaskterminal` 读回是空字符串，相当于绑定被静默丢弃。下次再打开编辑弹窗，分组选择丢失。

**根因（已验证）**：远端固件 `V2.6.1.0` 的 `modifytask` / `addtask` 的 `terminal` 字段**只接受 `2_` 前缀**（未分组终端 ID）。`1_` 前缀的分组 ID 写入接口虽然返回 `ok`，实际并未持久化。验证方式：对同一个 taskid 用不同前缀调 `modifytask` 然后立刻 `gettaskterminal`，只有 `2_` 前缀的值能读回。

**附加限制**：当前接口集没有提供"分组 → 该分组下所有终端 ID"的查询能力，前端无法自动将分组展开成终端列表来绕过这个 bug。

**临时处置**：
- 前端 UI 维持现状：分组与独立终端都可选，分组提交后由远端决定如何处理。
- 不在前端拦截 / 提示分组选择，避免干扰用户日常操作；固件修复后无需调整前端即可自动恢复。
- 客户端用 `localStorage` 缓存每个任务的分组选择（key=`lt:task_group_selections`，仅缓存 `1_` 前缀项），编辑弹窗打开时把缓存的分组与远端读回的独立终端合并后展示，避免"选了 123，下次打开看不到"的困惑。任务被删除时缓存对应项也会清掉。
- 未注册任何独立终端的设备（`getterminal` item 为空），作息任务实际依赖 `area0`–`area7` 本地分区广播，`terminal` 字段留空即可。

**待跟进**：等待设备厂商修复 `modifytask` 对 `1_` 前缀的支持，或新增 `bindgroup` 类专用接口，届时取消前端的 confirm 提示并直接透传分组绑定。
