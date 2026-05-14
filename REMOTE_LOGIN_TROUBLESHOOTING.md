# 远端登录排障记录

本文记录航天广电 action 接口登录链路的已知结论和排查顺序，避免重复踩坑。

## 当前架构

- 前端继续调用本地后端：`/auth/login`、`/api/light/*`。
- 后端再统一对接远端 action/swagger 接口：`/action/login`、`/action/getmedia` 等。
- 不建议浏览器前端直接调用远端接口。

原因：

- 远端设备通常不会配置浏览器跨域所需的 CORS。
- 远端登录参数可能出现在 query 中，前端直连会扩大账号密码暴露面。
- 远端登录态、cookie、HTML 登录页识别、重试和 diagnostics 需要统一收敛在后端。
- 用户浏览器不一定能稳定访问设备内网地址，但后端部署机通常更适合做统一出口。

## 已确认结论

- 远端默认账号是 `useradmin`，不要误用本地后台账号如 `admin`。
- cookie 只作为诊断和兼容保留，不作为登录成功的必要条件。
- 远端登录成功和失败都可能返回 HTML，不能只用“是否 HTML”判断登录态。
- `login.txt` 是未登录或登录失败页面样本。
- `loginsucess.txt` 是登录成功后的后台主界面样本。
- 当前成功判定应以业务探测为准：登录后请求只读接口，如 `/action/getmedia`，如果仍返回登录页，说明远端没有进入可用登录态。

## 常见错误含义

### `Remote login completed but business probe still returned login page.`

含义：

- 后端已经尝试远端登录。
- 登录后立刻调用业务探测接口。
- 探测接口仍返回 `login.txt` 这类登录页。

这通常不是 cookie 问题，而是远端没有接受本次登录，或登录态没有绑定到后续业务请求。

排查顺序：

1. 确认前端登录账号是否为 `useradmin`。
2. 确认密码是否为远端设备密码，不是本地系统密码。
3. 确认当前远端地址是否正确，例如 `http://192.168.x.x`，不要误选旧 IP 或错误端口。
4. 查看 diagnostics 中每次登录尝试的 `login_attempt_mode`、`url`、`response_url`、`html_kind`、`raw_preview`。
5. 如果三种登录方式都返回登录页，再确认远端是否要求额外登录步骤、Referer、User-Agent 或先访问登录页建立状态。
6. 如果登录探测接口 `/action/getmedia` 不适用于某台设备，再考虑增加多个只读探测接口，例如 `getterminal` 或 `getbasicinfo`。

## diagnostics 重点字段

排查远端登录时优先看这些字段：

- `phase`
- `login_attempt_mode`
- `method`
- `url`
- `response_url`
- `status_code`
- `html_kind`
- `login_page_like`
- `app_shell_like`
- `set_cookie_present`
- `set_cookie_has_action_session`
- `cookies_before`
- `cookies_after`
- `cookie_changed`
- `business_probe_attempted`
- `business_probe_success`
- `business_probe_path`
- `raw_preview`
- `error`

## 性能优化方向

当前不建议把前端改成直连远端。优先在后端优化：

- 对 `/api/light/resources` 增加短 TTL 缓存，减少重复拉取媒体、终端、基础信息。
- 避免每次请求都做不必要的登录探测。
- 对 `media`、`terminal`、`basic` 这类只读资源做并行拉取或缓存复用。
- 保留 diagnostics，确保现场问题能定位到具体远端请求和 HTML 类型。

## 相关验证

如果只修改本文档，不需要运行测试。

如果修改远端登录、探测、缓存或 `/api/light/resources` 行为，运行：

```powershell
C:\Users\Taric\anaconda3\python.exe -m pytest -q backend\tests\test_light_routes.py backend\tests\test_api_public_remote_settings.py
```
