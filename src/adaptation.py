"""
Dynamic adaptation layer: loads new location/media assets and provides fuzzy lookup.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

try:
    from rapidfuzz import process as fuzz_process
except Exception:  # pragma: no cover - optional dependency
    fuzz_process = None


@dataclass
class AssetIndex:
    names: List[str]
    name_to_meta: Dict[str, dict]

    def fuzzy_match(self, query: str, score_cutoff: float = 70.0) -> Tuple[Optional[str], Optional[dict], float]:
        if not fuzz_process or not self.names or not query:
            return None, None, 0.0
        res = fuzz_process.extractOne(query, self.names, score_cutoff=score_cutoff)
        if not res:
            return None, None, 0.0
        name, score, _ = res
        return name, self.name_to_meta.get(name), score / 100.0
    
    # 增加这个方法方便调试
    def __len__(self):
        return len(self.names)
    
    def __contains__(self, item):
        return item in self.names


def _extract_name(item: dict) -> str:
    """
    Prefer `name`, then `medianame`, then `taskname`.
    """
    for key in ("name", "medianame", "taskname", "zonename", "audio", "customName"):
        if key in item and item[key]:
            val = str(item[key]).strip()
            if val and val.lower() != "string": # 过滤掉默认生成的无效值
                return val
    return ""

def _resolve_json_path(path: Union[Path, str]) -> Path:
    # 兼容字符串路径
    if isinstance(path, str):
        path = Path(path)
        
    if path.exists():
        return path
    candidate = path.with_suffix(".json")
    if candidate.exists():
        return candidate
    return path
def _load_asset_file(path: Union[Path, str]) -> AssetIndex:
    names: List[str] = []
    name_to_meta: Dict[str, dict] = {}
    
    path_obj = _resolve_json_path(path)
    
    # 【调试】打印加载路径，确保没读错文件
    # print(f"【Adaptation】Loading asset from: {path_obj.absolute()}")

    if not path_obj.exists():
        print(f"【Adaptation】Warning: File not found: {path_obj}")
        return AssetIndex(names, name_to_meta)
        
    try:
        content = path_obj.read_text(encoding="utf-8")
        if not content.strip():
            return AssetIndex(names, name_to_meta)
        payload = json.loads(content)
    except Exception as e:
        print(f"【Adaptation】Error reading {path_obj}: {e}")
        return AssetIndex(names, name_to_meta)
        
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        items = payload if isinstance(payload, list) else [] # 兼容直接是 list 的情况

    for item in items:
        if not isinstance(item, dict):
            continue
        name = _extract_name(item)
        if not name:
            continue
        names.append(name)
        name_to_meta[name] = item
        
    return AssetIndex(names, name_to_meta)


def _load_task_file(path: Union[Path, str]) -> AssetIndex:
    names: List[str] = []
    name_to_meta: Dict[str, dict] = {}
    
    path_obj = _resolve_json_path(path)

    if not path_obj.exists():
        print(f"【Adaptation】Warning: Task file not found: {path_obj}")
        return AssetIndex(names, name_to_meta)
        
    try:
        content = path_obj.read_text(encoding="utf-8")
        if not content.strip():
            return AssetIndex(names, name_to_meta)
        payload = json.loads(content)
    except Exception as e:
        print(f"【Adaptation】Error reading task file {path_obj}: {e}")
        return AssetIndex(names, name_to_meta)
        
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        items = payload if isinstance(payload, list) else []

    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        
        # === 【修改版】只加载任务的专属名称 ===
        # 去掉了 'audio' 和 'medianame'，避免不同任务因使用相同音频而冲突
        possible_names = set()
        
        for key in ["taskname", "name", "customName"]: # <--- 只保留这三个
            val = item.get(key)
            if val:
                val_str = str(val).strip()
                # 过滤掉无意义的默认值
                if val_str and val_str.lower() not in ("string", "0", "null", "none"):
                    possible_names.add(val_str)
        
        for name in possible_names:
            names.append(name)
            name_to_meta[name] = item
            count += 1
            
    print(f"【Adaptation】Loaded {count} task names from {len(items)} items.")
    return AssetIndex(names, name_to_meta)

def load_adaptation_assets(
    media_path: Union[Path, str],
    loc_path: Union[Path, str],
    task_path: Union[Path, str] | None = None,
    zone_path: Union[Path, str] | None = None,
) -> Tuple[AssetIndex, AssetIndex, AssetIndex, AssetIndex]:
    """
    Load media/location/task/zone assets for dynamic adaptation.
    """
    media_index = _load_asset_file(media_path)
    loc_index = _load_asset_file(loc_path)
    task_index = _load_task_file(task_path) if task_path else AssetIndex([], {})
    zone_index = _load_asset_file(zone_path) if zone_path else AssetIndex([], {})
    
    return media_index, loc_index, task_index, zone_index