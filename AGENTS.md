# AI Speaker Project - Agent Guide

> AI 校园广播智能体项目开发指南。本文档面向 AI 编码助手，帮助快速理解项目结构、技术栈和开发规范。

## 项目概述

这是一个基于 RBT3 (hfl/chinese-rbt3) 的智能校园广播 NLU 系统，实现从自然语言理解到设备控制的全链路闭环。系统不仅能理解自然语言意图，还能将语义直接编译为可落地的广播调度与终端控制指令，并对接真实远端设备接口闭环执行。

### 核心价值
- **联合 NLU 架构**: 单次推理同时输出 `intent + slots`，减少多模型串联开销
- **时空语义编译器**: 支持周维度+日期维度作息迁移/对调
- **执行安全层**: 关键操作支持失败回滚，避免远端半成功导致的数据污染
- **全链路闭环**: 从对话输入到远端任务执行、终端检测、结果回写

## 技术栈

| 层级 | 技术 |
|-----|------|
| NLU 模型 | PyTorch + Transformers (RBT3) + torchcrf |
| API 服务 | FastAPI + uvicorn |
| 前端 | Vue.js 2.x + Element UI |
| 辅助库 | RapidFuzz (模糊匹配), JioNLP (时间解析) |
| 测试 | pytest |

### 依赖安装

```bash
pip install -r requirements.txt
```

主要依赖包括：
- `torch>=2.0` - 深度学习框架
- `transformers>=4.30` - 预训练模型库
- `datasets>=2.14` - 数据集处理
- `torchcrf>=1.1` - CRF 层实现
- `fastapi>=0.100` + `uvicorn[standard]>=0.23` - API 服务
- `rapidfuzz>=3.0` - 模糊字符串匹配（可选）

## 项目结构

```
c:\AI_Speaker_Project/
├── src/                      # 核心 NLU 引擎
│   ├── engine.py            # 推理引擎（意图识别 + 槽位填充）
│   ├── preprocessor.py      # 数据预处理，生成 BIO 标注
│   ├── trainer.py           # RBT3 + CRF 联合训练
│   ├── session_manager.py   # 对话状态管理（Session/DM）
│   ├── response_manager.py  # NLG 回复生成
│   ├── speech_templates.py  # 话术模板
│   ├── evaluate.py          # 批量评测脚本
│   ├── adaptation.py        # 资源适配（词典加载）
│   └── data_clean_balanced.json  # 训练数据
├── backend/                  # FastAPI 后端服务
│   ├── api_public.py        # 主 API 入口（含意图执行逻辑）
│   ├── app.py               # FastAPI 应用入口
│   ├── config.py            # 配置常量
│   ├── models.py            # Pydantic 模型定义
│   ├── routes/              # 路由模块
│   │   ├── assistant.py     # 助手对话路由
│   │   ├── admin.py         # 管理路由
│   │   ├── terminal.py      # 终端代理路由
│   │   └── debug.py         # 调试路由
│   ├── services/            # 服务层
│   │   ├── cache.py         # 内存缓存
│   │   ├── data_store.py    # JSON 数据存储
│   │   ├── helpers.py       # 工具函数
│   │   └── remote_client.py # 远端 HTTP 客户端
│   ├── data/                # 运行时数据（词典、作息表等）
│   │   ├── all_audio.json   # 音频资源词典
│   │   ├── all_loc.json     # 终端/位置词典
│   │   ├── all_task.json    # 任务词典
│   │   ├── broadcast_schedules.json  # 广播作息方案
│   │   ├── task_overrides.json       # 任务覆盖配置
│   │   └── templates.json            # 作息模板
│   └── tests/               # 后端测试
├── web/                      # Vue.js 前端应用
│   ├── package.json         # Node.js 依赖
│   ├── src/                 # 前端源码
│   ├── dist/                # 构建输出
│   └── vue.config.js        # Vue 配置
├── data/                     # 训练/测试数据
│   ├── trainning_data.xlsx  # 训练数据（Excel）
│   ├── test_dataset.xlsx    # 测试数据
│   ├── label_config.json    # 标签映射配置
│   └── hf_cache/            # HuggingFace 缓存
├── models/                   # 预训练模型目录（gitignored）
│   └── joint_rbt3/          # 训练输出目录
│       └── joint_model.pt   # 训练好的模型权重
├── scripts/                  # 实用脚本
│   └── test_engine_smoke.py # 引擎冒烟测试
├── main.py                   # CLI 入口（交互式推理）
├── requirements.txt          # Python 依赖
└── skills-repo/             # Kimi Skills 参考文档
    └── ai-speaker-project/
        ├── SKILL.md         # Skill 主文档
        └── references/      # 详细参考文档
```

## 意图体系 (v3.1)

系统共支持 **30 个意图**（含 `none`），分为以下类别：

### 核心意图（3.1）
| intent | 说明 |
|--------|------|
| `move_schedule` | 单向挪动作息（同方案内） |
| `swap_schedule` | 双向对调作息（同方案内） |
| `cancel_schedule` | 取消作息任务 |
| `create_schedule` | 新建作息方案 |
| `play_media` | 即时媒体播放 |
| `replace_media` | 替换媒体 |

### 其他意图（3.2）
- **作息启停**: `enable_schedule`, `disable_schedule`
- **作息管理**: `shift_schedule_later`, `shift_schedule_earlier`, `delete_schedule`, `replace_media_in_task`
- **终端管理**: `query_terminal`, `enable_terminal`, `disable_terminal`, `sync_terminal_time`, `check_terminal`
- **分区管理**: `create_zone`, `delete_zone`, `add_terminal_to_zone`, `remove_terminal_from_zone`
- **任务管理**: `add_terminal_to_task`, `remove_terminal_from_task`, `query_task`, `play_task`, `stop_task`
- **播放控制**: `pause_task`, `resume_task`
- **其他**: `adjust_volume`, `broadcast_emergency`, `none`

### 槽位总表
| 槽位 | 说明 |
|------|------|
| `source_time` | 源时间（起点） |
| `end_time` | 目标时间/结束时间 |
| `time_offset` | 时间位移量（如"30分钟"） |
| `play_duration` | 播放时长 |
| `schedule_name` | 作息方案名称 |
| `schedule_kind` | 作息场景类型（小学/中学等） |
| `media_name` / `new_media_name` | 媒体名称 |
| `task_name` / `task_type` | 任务名称/类型 |
| `terminal_id` / `terminal_name` | 终端编号/名称 |
| `zone_name` | 分区名称 |
| `volume` | 音量表达 |
| `play_count` | 播放次数 |

## 常用命令

### 训练流程
```bash
# 1. 数据预处理（生成 HF Dataset 与 label_config.json）
python src/preprocessor.py

# 2. 训练模型（输出 models/joint_rbt3/joint_model.pt）
python src/trainer.py

# 3. 批量评测
python src/evaluate.py
```

### 启动服务
```bash
# 启动 FastAPI 服务（开发模式）
python -m uvicorn backend.api_public:app --reload --port 5012

# 或使用新的模块化入口
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000

# CLI 交互模式
python main.py
```

### 测试
```bash
# 引擎冒烟测试
python scripts/test_engine_smoke.py

# 后端测试
cd backend
pytest tests/

# 前端测试（在 web/ 目录下）
cd web
npm run test:unit
```

### API 测试示例
```bash
# 测试推理接口
curl -X POST http://localhost:5012/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "明天下午四点播放国歌", "session_id": "test123"}'

# 测试对话接口
curl -X POST http://localhost:5012/assistant/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "音量调大一点"}'
```

## 代码规范

### Python 代码风格
- 使用 `from __future__ import annotations` 启用类型注解
- 类型注解：使用 `typing` 模块，如 `Dict[str, object]`, `Optional[str]`
- 使用 dataclass 定义配置类
- 导入顺序：标准库 → 第三方库 → 本地模块
- 使用相对导入处理模块内引用，提供 ImportError fallback

### 示例模式
```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# 第三方库
import torch
from transformers import AutoTokenizer

# 本地模块（带 fallback）
try:
    from .preprocessor import DATA_DIR
    from .trainer import JointRBT3Model
except ImportError:  # pragma: no cover - fallback for script usage
    from preprocessor import DATA_DIR
    from trainer import JointRBT3Model


@dataclass
class EngineConfig:
    model_dir: Path = Path("models/joint_rbt3")
    max_length: int = 128
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
```

### 文件编码
- 所有 Python 文件使用 UTF-8 编码
- 文件头注明编码：`# -*- coding: utf-8 -*-`（可选，Python 3 默认 UTF-8）

### Codex 执行原则（精简版）
- 先理解需求，再动代码；若需求、边界或数据来源不清楚，先确认假设。
- 优先阅读相关入口、调用链和测试，再决定修改点；不要凭印象改动。
- 默认选择最简单、最直接的实现；不要为“以后可能需要”提前抽象。
- 新逻辑优先复用现有函数、数据结构和约定；只有在复用明显不合适时再新增抽象。
- 修改范围应尽量小，只改与当前需求直接相关的代码和配置。
- 不要顺手重构无关模块；若发现独立问题，应单独记录，而不是混在当前改动中。
- 对关键行为先明确成功条件，再实现；避免“代码看起来合理但无法验证”。
- 能用现有测试覆盖的改动，优先补充或更新测试；不能自动验证时，要说明人工验证方式。
- 发现假设依赖外部接口、运行时数据或历史兼容逻辑时，先核对真实来源，再落地实现。
- 优先修正根因，不用堆叠特判掩盖问题。
- 避免一次性引入多种方案；先交付最小可工作的版本，再按反馈迭代。
- 输出结果应说明：改了什么、为什么这样改、如何验证、还有哪些已知边界。

## 配置说明

### 环境变量
| 变量名 | 说明 | 默认值 |
|-------|------|-------|
| `REMOTE_BASE_URL` | 远端设备 API 地址 | `http://117.40.88.155:99/api` |
| `REMOTE_USERNAME` | API 用户名 | `admin` |
| `REMOTE_PASSWORD` | API 密码 | `123456` |
| `REMOTE_TIMEOUT` | 请求超时(秒) | `15` |
| `REMOTE_CACHE_SECONDS` | 缓存时间(秒) | `8` |
| `DEBUG_REMOTE` | 启用调试日志 | `1` |

### 数据文件路径
数据文件默认存放在 `backend/data/` 目录：
- `all_audio.json` - 音频资源词典
- `all_loc.json` - 终端/位置词典
- `all_task.json` - 任务词典
- `broadcast_schedules.json` - 广播作息方案
- `task_overrides.json` - 任务覆盖配置

## 开发工作流

### 添加新意图

1. **在 `PHASE1_INTENTS` 中注册意图**
   - 文件: `backend/api_public.py`
   - 将意图名称添加到 `PHASE1_INTENTS` 集合

2. **实现意图处理器**
   - 创建 `_apply_{intent_name}()` 函数
   - 在 `_apply_phase1_intent()` 中添加分发逻辑

3. **添加 NLU 训练数据**
   - 更新 `data/training_data.xlsx`
   - 重新运行 `src/preprocessor.py` 生成数据集

4. **测试**
   - 使用 `/debug/test_phase1_intent` 端点测试
   - 运行集成测试

### 调试端点

```bash
# 快速测试意图（无需 NLU）
POST /debug/test_phase1_intent
{
    "intent": "adjust_volume",
    "text": "音量增加",
    "slots": {"volume": "增加"}
}
```

## 测试策略

### 测试分层
1. **单元测试**: 针对单个函数/类（`backend/tests/test_*.py`）
2. **集成测试**: 端到端 API 测试
3. **冒烟测试**: 快速验证核心功能（`scripts/test_engine_smoke.py`）

### 运行测试
```bash
# 全部测试
pytest backend/tests/

# 特定测试文件
pytest backend/tests/test_api_public_phase3_intents.py

# 带日志输出
pytest backend/tests/ -v -s
```

## 部署注意事项

### 模型文件
- `models/` 目录在 `.gitignore` 中，需单独准备
- 生产环境需确保 `models/joint_rbt3/joint_model.pt` 存在

### 数据持久化
- `backend/data/` 目录包含运行时数据
- 历史版本备份存放在 `backend/data/.history/`

### 网络依赖
- 默认需要连接远端设备 API（可通过环境变量配置）
- 如需离线运行，需配置本地模拟数据

## 安全考虑

1. **API 认证**: 远端 API 使用用户名/密码认证，通过环境变量配置
2. **CORS**: 开发环境允许所有来源，生产环境应限制域名
3. **输入验证**: 使用 Pydantic 模型进行请求校验
4. **执行安全**: 关键操作支持失败回滚机制

## 参考资料

- `RBT3_ARCHITECTURE.md` - 技术架构方案
- `AI_RESUME_ARCHITECTURE.md` - 项目亮点与简历用语
- `ADJUST_VOLUME_FEATURE.md` - 音量调整功能详细设计
- `ADJUST_VOLUME_TEST_GUIDE.md` - 音量调整测试指南
- `skills-repo/ai-speaker-project/` - Kimi Skill 参考文档
