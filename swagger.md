# My Collection（按 2222.md 文件规范整理）

## 1. 概述

- 集合名称：`My Collection`
- Base URL：`http://192.168.1.88`
- 接口数量：38

## 2. 接口目录

| # | 接口名 | 方法 | Path |
|---:|---|---|---|
| 1 | `login` | `POST` | `/action/login` |
| 2 | `gettaskinfo` | `POST` | `/action/basicparameters` |
| 3 | `taskstart` | `POST` | `/action/taskstart` |
| 4 | `taskstop` | `POST` | `/action/taskstop` |
| 5 | `gettaskmedia` | `POST` | `/action/gettaskmedia` |
| 6 | `gettaskterminal` | `POST` | `/action/gettaskterminal` |
| 7 | `getmedia` | `POST` | `/action/getmedia` |
| 8 | `getterminal` | `POST` | `/action/getterminal` |
| 9 | `exectemptask` | `POST` | `/action/executetmptask` |
| 10 | `stoptemptask` | `POST` | `/action/stoptmptask` |
| 11 | `addholiday` | `POST` | `/action/addholiday` |
| 12 | `modifyholiday` | `POST` | `/action/modifyholiday` |
| 13 | `delholiday` | `POST` | `/action/delholiday` |
| 14 | `getholiday` | `POST` | `/action/getholiday` |
| 15 | `getallsech` | `POST` | `/action/getallsech` |
| 16 | `getbaseinfo` | `POST` | `/action/getbasicinfo` |
| 17 | `getExtarea` | `POST` | `/action/getbasicinfo` |
| 18 | `setExtarea` | `POST` | `/action/addterminal` |
| 19 | `delExtarea` | `POST` | `/action/delterminal` |
| 20 | `getquicktask` | `POST` | `/action/getquicktask` |
| 21 | `getfiretask` | `POST` | `/action/getfiretask` |
| 22 | `getextgroup` | `POST` | `/action/getextgroup` |
| 23 | `modifyExtarea` | `POST` | `/action/modifyterminal` |
| 24 | `addgroup` | `POST` | `/action/addgroup` |
| 25 | `modifygroup` | `POST` | `/action/modifygroup` |
| 26 | `delgroup` | `POST` | `/action/deltegroup` |
| 27 | `getterminalid` | `POST` | `/action/getterminalid` |
| 28 | `opensech` | `POST` | `/action/opensech` |
| 29 | `saveprogramname` | `POST` | `/action/saveprogramname` |
| 30 | `copygudingprogram` | `POST` | `/action/copygudingprogram` |
| 31 | `deletegudingprogram` | `POST` | `/action/deletegudinggrogram` |
| 32 | `activeprogram` | `POST` | `/action/activeprogram` |
| 33 | `addtask` | `POST` | `/action/addtask` |
| 34 | `modifytask` | `POST` | `/action/modifytask` |
| 35 | `deltask` | `POST` | `/action/deletetask` |
| 36 | `setvolume` | `POST` | `/action/setvolume` |
| 37 | `modifyyaokongtask` | `POST` | `/action/yaokongtask` |
| 38 | `modifyalarm` | `POST` | `/action/modifyalarm` |

---

## 3. 接口详情

### 3.1 `login`

- 功能：login（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/login?username=useradmin&password=123456`
- Base URL：`http://192.168.1.88`
- Path：`/action/login`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `username` | 视业务 |  | `useradmin` |
    | `password` | 视业务 |  | `123456` |
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/login?username=useradmin&password=123456'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.2 `gettaskinfo`

- 功能：gettaskinfo（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/basicparameters`
- Base URL：`http://192.168.1.88`
- Path：`/action/basicparameters`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/basicparameters'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.3 `taskstart`

- 功能：taskstart（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/taskstart`
- Base URL：`http://192.168.1.88`
- Path：`/action/taskstart`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `taskid` | `text` | 视业务 | 任务id | `119` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/taskstart' --data-urlencode 'taskid=119'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.4 `taskstop`

- 功能：taskstop（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/taskstop`
- Base URL：`http://192.168.1.88`
- Path：`/action/taskstop`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `taskid` | `text` | 视业务 | 任务id | `119` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/taskstop' --data-urlencode 'taskid=119'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.5 `gettaskmedia`

- 功能：gettaskmedia（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/gettaskmedia`
- Base URL：`http://192.168.1.88`
- Path：`/action/gettaskmedia`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `taskid` | `text` | 视业务 | 任务id | `120` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/gettaskmedia' --data-urlencode 'taskid=120'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.6 `gettaskterminal`

- 功能：gettaskterminal（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/gettaskterminal`
- Base URL：`http://192.168.1.88`
- Path：`/action/gettaskterminal`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `taskid` | `text` | 视业务 | 任务id | `120` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/gettaskterminal' --data-urlencode 'taskid=120'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.7 `getmedia`

- 功能：getmedia（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getmedia`
- Base URL：`http://192.168.1.88`
- Path：`/action/getmedia`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getmedia'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.8 `getterminal`

- 功能：getterminal（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getterminal`
- Base URL：`http://192.168.1.88`
- Path：`/action/getterminal`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getterminal'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.9 `exectemptask`

- 功能：exectemptask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/executetmptask`
- Base URL：`http://192.168.1.88`
- Path：`/action/executetmptask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `media` | `text` | 视业务 | 媒体id | `360,361` |
      | `terminal` | `text` | 视业务 | 终端id,1_70（1表示分组，分组id=70），2_447(2表示未分组，终端id=447) | `1_70,2_447,2_448` |
      | `playmode` | `text` | 视业务 | 0=时长，1=次数 | `0` |
      | `timehour` | `text` | 视业务 | 播放时 | `0` |
      | `timeminute` | `text` | 视业务 | 播放分 | `2` |
      | `timesecond` | `text` | 视业务 | 播放秒 | `0` |
      | `times` | `text` | 视业务 | 次数 | `1` |
      | `volume` | `text` | 视业务 | 音量（0-100） | `80` |
      | `random` | `text` | 视业务 | 0=顺序播放，1=随机 | `0` |
      | `area0` | `text` | 视业务 | 分区1 | `1` |
      | `area1` | `text` | 视业务 |  | `1` |
      | `area2` | `text` | 视业务 |  | `1` |
      | `area3` | `text` | 视业务 |  | `` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/executetmptask' --data-urlencode 'media=360,361' --data-urlencode 'terminal=1_70,2_447,2_448' --data-urlencode 'playmode=0' --data-urlencode 'timehour=0' --data-urlencode 'timeminute=2' --data-urlencode 'timesecond=0' --data-urlencode 'times=1' --data-urlencode 'volume=80' --data-urlencode 'random=0' --data-urlencode 'area0=1' --data-urlencode 'area1=1' --data-urlencode 'area2=1' --data-urlencode 'area3='
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.10 `stoptemptask`

- 功能：stoptemptask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/stoptmptask`
- Base URL：`http://192.168.1.88`
- Path：`/action/stoptmptask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/stoptmptask'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.11 `addholiday`

- 功能：addholiday（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/addholiday`
- Base URL：`http://192.168.1.88`
- Path：`/action/addholiday`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `holidayname` | `text` | 视业务 | 节日名称 | `22` |
      | `startdate` | `text` | 视业务 |  | `2026-04-15` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/addholiday' --data-urlencode 'holidayname=22' --data-urlencode 'startdate=2026-04-15'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.12 `modifyholiday`

- 功能：modifyholiday（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/modifyholiday?taskid=8`
- Base URL：`http://192.168.1.88`
- Path：`/action/modifyholiday`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `taskid` | 视业务 | 任务id | `8` |
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `holidayname` | `text` | 视业务 | 节日名称 | `22` |
      | `startdate` | `text` | 视业务 | 开始日期 | `2026-04-15` |
      | `enddate` | `text` | 视业务 | 结束日期 | `2026-04-15` |
      | `deftmedias` | `text` | 视业务 | 1=启用，0=停用 | `1` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/modifyholiday?taskid=8' --data-urlencode 'holidayname=22' --data-urlencode 'startdate=2026-04-15' --data-urlencode 'enddate=2026-04-15' --data-urlencode 'deftmedias=1'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.13 `delholiday`

- 功能：delholiday（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/delholiday`
- Base URL：`http://192.168.1.88`
- Path：`/action/delholiday`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `taskid` | `text` | 视业务 |  | `9` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/delholiday' --data-urlencode 'taskid=9'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.14 `getholiday`

- 功能：getholiday（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getholiday`
- Base URL：`http://192.168.1.88`
- Path：`/action/getholiday`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getholiday'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.15 `getallsech`

- 功能：getallsech（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getallsech`
- Base URL：`http://192.168.1.88`
- Path：`/action/getallsech`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getallsech'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.16 `getbaseinfo`

- 功能：getbaseinfo（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getbasicinfo`
- Base URL：`http://192.168.1.88`
- Path：`/action/getbasicinfo`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getbasicinfo'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.17 `getExtarea`

- 功能：getExtarea（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getbasicinfo`
- Base URL：`http://192.168.1.88`
- Path：`/action/getbasicinfo`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getbasicinfo'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.18 `setExtarea`

- 功能：setExtarea（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/addterminal`
- Base URL：`http://192.168.1.88`
- Path：`/action/addterminal`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `terminalname` | `text` | 视业务 | 扩展终端分区名称 | `9` |
      | `terminaladdr` | `text` | 视业务 | 扩展终端分区地址 | `10` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/addterminal' --data-urlencode 'terminalname=9' --data-urlencode 'terminaladdr=10'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.19 `delExtarea`

- 功能：delExtarea（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/delterminal`
- Base URL：`http://192.168.1.88`
- Path：`/action/delterminal`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/delterminal'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.20 `getquicktask`

- 功能：getquicktask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getquicktask`
- Base URL：`http://192.168.1.88`
- Path：`/action/getquicktask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getquicktask'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.21 `getfiretask`

- 功能：getfiretask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getfiretask`
- Base URL：`http://192.168.1.88`
- Path：`/action/getfiretask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getfiretask'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.22 `getextgroup`

- 功能：getextgroup（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getextgroup`
- Base URL：`http://192.168.1.88`
- Path：`/action/getextgroup`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getextgroup'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.23 `modifyExtarea`

- 功能：modifyExtarea（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/modifyterminal`
- Base URL：`http://192.168.1.88`
- Path：`/action/modifyterminal`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `terminalname` | `text` | 视业务 | 扩展终端分区名称 | `31` |
      | `terminaladdr` | `text` | 视业务 | 扩展终端分区地址 | `3` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/modifyterminal' --data-urlencode 'terminalname=31' --data-urlencode 'terminaladdr=3'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.24 `addgroup`

- 功能：addgroup（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/addgroup?media2=452,451`
- Base URL：`http://192.168.1.88`
- Path：`/action/addgroup`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `media2` | 视业务 | 扩展终端分区id | `452,451` |
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `groupname` | `text` | 视业务 | 分组名称 | `852` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/addgroup?media2=452,451' --data-urlencode 'groupname=852'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.25 `modifygroup`

- 功能：modifygroup（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/modifygroup?media2=449,451&groupid=72`
- Base URL：`http://192.168.1.88`
- Path：`/action/modifygroup`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `media2` | 视业务 | 扩展终端分区id | `449,451` |
    | `groupid` | 视业务 | 分组id | `72` |
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `media` | `text` | 视业务 | 分组id | `72` |
      | `groupname` | `text` | 视业务 | 分组名称 | `3999` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/modifygroup?media2=449,451&groupid=72' --data-urlencode 'media=72' --data-urlencode 'groupname=3999'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.26 `delgroup`

- 功能：delgroup（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/deltegroup`
- Base URL：`http://192.168.1.88`
- Path：`/action/deltegroup`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`urlencoded`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `groupid` | `text` | 视业务 | 分组id | `71` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/deltegroup' --data-urlencode 'groupid=71'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.27 `getterminalid`

- 功能：getterminalid（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/getterminalid`
- Base URL：`http://192.168.1.88`
- Path：`/action/getterminalid`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `groupid` | `text` | 视业务 | 分组id | `70` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/getterminalid' --data-urlencode 'groupid=70'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.28 `opensech`

- 功能：opensech（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/opensech?id=1`
- Base URL：`http://192.168.1.88`
- Path：`/action/opensech`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `id` | 视业务 | 方案id | `1` |
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/opensech?id=1'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.29 `saveprogramname`

- 功能：saveprogramname（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/saveprogramname`
- Base URL：`http://192.168.1.88`
- Path：`/action/saveprogramname`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `id` | `text` | 视业务 | 方案id | `1` |
      | `name` | `text` | 视业务 | 方案名称 | `方案18` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/saveprogramname' --data-urlencode 'id=1' --data-urlencode 'name=方案18'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.30 `copygudingprogram`

- 功能：copygudingprogram（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/copygudingprogram`
- Base URL：`http://192.168.1.88`
- Path：`/action/copygudingprogram`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `id` | `text` | 视业务 | 新方案id(复制方案) | `5` |
      | `yuan` | `text` | 视业务 | 源方案id | `3` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/copygudingprogram' --data-urlencode 'id=5' --data-urlencode 'yuan=3'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.31 `deletegudingprogram`

- 功能：deletegudingprogram（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/deletegudinggrogram?id=3`
- Base URL：`http://192.168.1.88`
- Path：`/action/deletegudinggrogram`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `id` | 视业务 | 方案id(删除方案) | `3` |
  - Body 参数：
    无
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/deletegudinggrogram?id=3'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.32 `activeprogram`

- 功能：activeprogram（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/activeprogram`
- Base URL：`http://192.168.1.88`
- Path：`/action/activeprogram`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `id` | `text` | 视业务 | 方案id(启用方案) | `5` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/activeprogram' --data-urlencode 'id=5'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.33 `addtask`

- 功能：addtask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/addtask?id=1`
- Base URL：`http://192.168.1.88`
- Path：`/action/addtask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `id` | 视业务 | 方案id | `1` |
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `media` | `text` | 视业务 | 媒体id | `359,360,361` |
      | `terminal` | `text` | 视业务 | 分区id（2表示未分组） | `2_446,2_445` |
      | `taskname` | `text` | 视业务 | 任务名称 | `32222` |
      | `playhour` | `text` | 视业务 | 播放时 | `12` |
      | `playminute` | `text` | 视业务 | 播放分 | `10` |
      | `playsecond` | `text` | 视业务 | 播放秒 | `0` |
      | `playmode` | `text` | 视业务 | 播放时长或次数，0是时长，1是次数 | `0` |
      | `timehour` | `text` | 视业务 | 时长（时） | `3` |
      | `timeminute` | `text` | 视业务 | 时长(分) | `3` |
      | `timesecond` | `text` | 视业务 | 时长(秒) | `3` |
      | `times` | `text` | 视业务 | 播放次数（playmode=0，次数未生效） | `1` |
      | `volume` | `text` | 视业务 | 音量（0-100） | `80` |
      | `enableordis` | `text` | 视业务 | 启用=0，停用=1 | `0` |
      | `area0` | `text` | 视业务 | 分区1 | `1` |
      | `area1` | `text` | 视业务 | 分区2 | `1` |
      | `area2` | `text` | 视业务 | 分区3 | `1` |
      | `area3` | `text` | 视业务 | 分区4 | `1` |
      | `area4` | `text` | 视业务 | 分区5 | `1` |
      | `area5` | `text` | 视业务 | 分区6 | `1` |
      | `area6` | `text` | 视业务 | 功放电源 | `1` |
      | `area7` | `text` | 视业务 | 外控电源 | `0` |
      | `workmode` | `text` | 视业务 | 执行模式 每日=0，手动=1（手动日期全为0） | `0` |
      | `day0` | `text` | 视业务 | 周一 | `1` |
      | `day1` | `text` | 视业务 | 周二 | `1` |
      | `day2` | `text` | 视业务 | 周三 | `1` |
      | `day3` | `text` | 视业务 | 周四 | `1` |
      | `day4` | `text` | 视业务 | 周五 | `1` |
      | `day5` | `text` | 视业务 | 周六 | `1` |
      | `day6` | `text` | 视业务 | 周日 | `1` |
      | `pretime` | `text` | 视业务 | 功放预开 | `10` |
      | `delaytime` | `text` | 视业务 | 功放迟关 | `10` |
      | `random` | `text` | 视业务 | 随机播放 | `0` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/addtask?id=1' --data-urlencode 'media=359,360,361' --data-urlencode 'terminal=2_446,2_445' --data-urlencode 'taskname=32222' --data-urlencode 'playhour=12' --data-urlencode 'playminute=10' --data-urlencode 'playsecond=0' --data-urlencode 'playmode=0' --data-urlencode 'timehour=3' --data-urlencode 'timeminute=3' --data-urlencode 'timesecond=3' --data-urlencode 'times=1' --data-urlencode 'volume=80' --data-urlencode 'enableordis=0' --data-urlencode 'area0=1' --data-urlencode 'area1=1' --data-urlencode 'area2=1' --data-urlencode 'area3=1' --data-urlencode 'area4=1' --data-urlencode 'area5=1' --data-urlencode 'area6=1' --data-urlencode 'area7=0' --data-urlencode 'workmode=0' --data-urlencode 'day0=1' --data-urlencode 'day1=1' --data-urlencode 'day2=1' --data-urlencode 'day3=1' --data-urlencode 'day4=1' --data-urlencode 'day5=1' --data-urlencode 'day6=1' --data-urlencode 'pretime=10' --data-urlencode 'delaytime=10' --data-urlencode 'random=0'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.34 `modifytask`

- 功能：modifytask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/modifytask?taskid=119`
- Base URL：`http://192.168.1.88`
- Path：`/action/modifytask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `taskid` | 视业务 | 任务id | `119` |
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `media` | `text` | 视业务 | 媒体id | `359,360,361` |
      | `terminal` | `text` | 视业务 | 分区id（2表示未分组） | `2_446,2_445` |
      | `taskname` | `text` | 视业务 | 任务名称 | `32222` |
      | `playhour` | `text` | 视业务 | 播放时 | `12` |
      | `playminute` | `text` | 视业务 | 播放分 | `10` |
      | `playsecond` | `text` | 视业务 | 播放秒 | `0` |
      | `playmode` | `text` | 视业务 | 播放时长或次数，0是时长，1是次数 | `0` |
      | `timehour` | `text` | 视业务 | 时长（时） | `3` |
      | `timeminute` | `text` | 视业务 | 时长(分) | `3` |
      | `timesecond` | `text` | 视业务 | 时长(秒) | `3` |
      | `times` | `text` | 视业务 | 播放次数（playmode=0，次数未生效） | `1` |
      | `volume` | `text` | 视业务 | 音量（0-100） | `80` |
      | `enableordis` | `text` | 视业务 | 启用=0，停用=1 | `0` |
      | `area0` | `text` | 视业务 | 分区1 | `1` |
      | `area1` | `text` | 视业务 | 分区2 | `1` |
      | `area2` | `text` | 视业务 | 分区3 | `1` |
      | `area3` | `text` | 视业务 | 分区4 | `1` |
      | `area4` | `text` | 视业务 | 分区5 | `1` |
      | `area5` | `text` | 视业务 | 分区6 | `1` |
      | `area6` | `text` | 视业务 | 功放电源 | `1` |
      | `area7` | `text` | 视业务 | 外控电源 | `0` |
      | `workmode` | `text` | 视业务 | 执行模式 每日=0，手动=1（手动日期全为0） | `0` |
      | `day0` | `text` | 视业务 | 周一 | `1` |
      | `day1` | `text` | 视业务 | 周二 | `1` |
      | `day2` | `text` | 视业务 | 周三 | `1` |
      | `day3` | `text` | 视业务 | 周四 | `1` |
      | `day4` | `text` | 视业务 | 周五 | `1` |
      | `day5` | `text` | 视业务 | 周六 | `1` |
      | `day6` | `text` | 视业务 | 周日 | `1` |
      | `pretime` | `text` | 视业务 | 功放预开 | `10` |
      | `delaytime` | `text` | 视业务 | 功放迟关 | `10` |
      | `random` | `text` | 视业务 | 随机播放 | `0` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/modifytask?taskid=119' --data-urlencode 'media=359,360,361' --data-urlencode 'terminal=2_446,2_445' --data-urlencode 'taskname=32222' --data-urlencode 'playhour=12' --data-urlencode 'playminute=10' --data-urlencode 'playsecond=0' --data-urlencode 'playmode=0' --data-urlencode 'timehour=3' --data-urlencode 'timeminute=3' --data-urlencode 'timesecond=3' --data-urlencode 'times=1' --data-urlencode 'volume=80' --data-urlencode 'enableordis=0' --data-urlencode 'area0=1' --data-urlencode 'area1=1' --data-urlencode 'area2=1' --data-urlencode 'area3=1' --data-urlencode 'area4=1' --data-urlencode 'area5=1' --data-urlencode 'area6=1' --data-urlencode 'area7=0' --data-urlencode 'workmode=0' --data-urlencode 'day0=1' --data-urlencode 'day1=1' --data-urlencode 'day2=1' --data-urlencode 'day3=1' --data-urlencode 'day4=1' --data-urlencode 'day5=1' --data-urlencode 'day6=1' --data-urlencode 'pretime=10' --data-urlencode 'delaytime=10' --data-urlencode 'random=0'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.35 `deltask`

- 功能：deltask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/deletetask`
- Base URL：`http://192.168.1.88`
- Path：`/action/deletetask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `taskid` | `text` | 视业务 |  | `119` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/deletetask' --data-urlencode 'taskid=119'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.36 `setvolume`

- 功能：setvolume（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/setvolume`
- Base URL：`http://192.168.1.88`
- Path：`/action/setvolume`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    无
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `volume` | `text` | 视业务 | 音量 | `30` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/setvolume' --data-urlencode 'volume=30'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.37 `modifyyaokongtask`

- 功能：modifyyaokongtask（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/yaokongtask?taskid=13`
- Base URL：`http://192.168.1.88`
- Path：`/action/yaokongtask`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `taskid` | 视业务 | 任务id | `13` |
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `media` | `text` | 视业务 | 媒体id | `360,361` |
      | `terminal` | `text` | 视业务 | 终端分区,(1表示分组，70表示分组id,2=未分组，446=扩展分区id) | `1_70,2_446,2_450` |
      | `taskname` | `text` | 视业务 | 任务名称 | `2sks` |
      | `playmode` | `text` | 视业务 | 0=时长，1=次数 | `1` |
      | `timehour` | `text` | 视业务 | 时长（时） | `0` |
      | `timeminute` | `text` | 视业务 | 时长（分） | `0` |
      | `timesecond` | `text` | 视业务 | 时长（秒） | `0` |
      | `times` | `text` | 视业务 | 次数 | `1` |
      | `yaokong` | `text` | 视业务 | 遥控任务生效 | `null` |
      | `setenables` | `text` | 视业务 | 1=启用，0=停用 | `1` |
      | `area0` | `text` | 视业务 | 分区1 | `1` |
      | `area1` | `text` | 视业务 | 分区2 | `1` |
      | `area2` | `text` | 视业务 | 分区3 | `1` |
      | `area3` | `text` | 视业务 | 分区4 | `1` |
      | `area4` | `text` | 视业务 | 分区5 | `1` |
      | `area5` | `text` | 视业务 | 分区6 | `1` |
      | `area6` | `text` | 视业务 | 功放电源 | `1` |
      | `area7` | `text` | 视业务 | 外控电源 | `0` |
      | `quick` | `text` | 视业务 | 快捷键，没用 | `0` |
      | `volume` | `text` | 视业务 | 音量 | `60` |
      | `random` | `text` | 视业务 | 1=随机，0=顺序 | `0` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/yaokongtask?taskid=13' --data-urlencode 'media=360,361' --data-urlencode 'terminal=1_70,2_446,2_450' --data-urlencode 'taskname=2sks' --data-urlencode 'playmode=1' --data-urlencode 'timehour=0' --data-urlencode 'timeminute=0' --data-urlencode 'timesecond=0' --data-urlencode 'times=1' --data-urlencode 'yaokong=null' --data-urlencode 'setenables=1' --data-urlencode 'area0=1' --data-urlencode 'area1=1' --data-urlencode 'area2=1' --data-urlencode 'area3=1' --data-urlencode 'area4=1' --data-urlencode 'area5=1' --data-urlencode 'area6=1' --data-urlencode 'area7=0' --data-urlencode 'quick=0' --data-urlencode 'volume=60' --data-urlencode 'random=0'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

### 3.38 `modifyalarm`

- 功能：modifyalarm（Postman 未提供更详细说明时按接口名记录）
- 请求方式：`POST`
- 请求地址：`http://192.168.1.88/action/modifyalarm?taskid=13`
- Base URL：`http://192.168.1.88`
- Path：`/action/modifyalarm`
- 请求头（Headers）：
  - 无
- 参数约束：
  - Query 参数：
    | 参数 | 必填 | 说明 | 示例 |
    |---|---|---|---|
    | `taskid` | 视业务 | 任务id | `13` |
  - Body 参数：
    - 类型：`formdata`
      | 参数 | 类型 | 必填 | 说明 | 示例 |
      |---|---|---|---|---|
      | `media` | `text` | 视业务 | 媒体id | `360,361` |
      | `terminal` | `text` | 视业务 | 终端分区,(1表示分组，70表示分组id,2=未分组，446=扩展分区id) | `1_70,2_446,2_450` |
      | `alarmname` | `text` | 视业务 | 任务名称 | `2sks` |
      | `area0` | `text` | 视业务 | 分区1 | `1` |
      | `area1` | `text` | 视业务 | 分区2 | `1` |
      | `area2` | `text` | 视业务 | 分区3 | `1` |
      | `area3` | `text` | 视业务 | 分区4 | `1` |
      | `area4` | `text` | 视业务 | 分区5 | `1` |
      | `area5` | `text` | 视业务 | 分区6 | `1` |
      | `area6` | `text` | 视业务 | 功放电源 | `1` |
      | `area7` | `text` | 视业务 | 外控电源 | `0` |
      | `deftmedias` | `text` | 视业务 | 1=播放默认媒体。0=media栏生效 | `1` |
      | `volume` | `text` | 视业务 | 音量 | `60` |
- 示例（curl）：

```bash
curl -X POST 'http://192.168.1.88/action/modifyalarm?taskid=13' --data-urlencode 'media=360,361' --data-urlencode 'terminal=1_70,2_446,2_450' --data-urlencode 'alarmname=2sks' --data-urlencode 'area0=1' --data-urlencode 'area1=1' --data-urlencode 'area2=1' --data-urlencode 'area3=1' --data-urlencode 'area4=1' --data-urlencode 'area5=1' --data-urlencode 'area6=1' --data-urlencode 'area7=0' --data-urlencode 'deftmedias=1' --data-urlencode 'volume=60'
```
- 响应：
  - Postman collection 未提供示例响应（`response` 为空），请以实际返回为准。

