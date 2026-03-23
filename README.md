# Proxy Nodes Auto Aggregator

> **声明**
> 本仓库脚本仅供个人测试使用。数据均通过正则提取自公开的 GitHub 仓库。请勿用于商业用途或公开分享。

## 功能说明

本仓库通过 GitHub Actions 抓取代理节点并处理：

1. **自动发现 (`discover.py`)**：每周通过 GitHub API 搜索节点仓库。测试存在节点的仓库加入 `repositories.txt` 白名单，无效的加入 `blacklist.txt` 黑名单。
2. **节点提取 (`main.py`)**：每天拉取白名单仓库的内容，提取节点链接（支持 vmess, vless, trojan, ss, ssr, tuic, hy2, wg, socks5）。
3. **格式修正与过滤**：
   - VMESS：固定 `v` 为字符串 "2"，`port` 为整数类型。丢弃缺失必需字段或 ID 不是标准 UUID 格式的节点。
   - 其他协议：拦截无端口的链接，清理尾部多余字符。
4. **去重与输出**：以核心配置参数作为唯一标识进行去重。最终数据经过 Base64 编码，输出到 `sub.txt`。

## 使用方法

### 1. 运行环境配置
项目通过 GitHub Actions 运行在 Python 3.10 虚拟环境中：
- **定时任务**：
  - `discover.yml`：每周运行一次，寻找新仓库。
  - `update.yml`：每天运行一次，抓取并生成节点文件。
- **权限设置**：进入本仓库的 `Settings` -> `Actions` -> `General` -> `Workflow permissions`，勾选 **`Read and write permissions`** 并保存。若不设置此项，脚本将无法写入并更新 `sub.txt`。
- **环境变量设置**（可选）：在 `Settings -> Secrets and variables -> Actions` 中新建一个 `GITHUB_TOKEN`，以避免脚本在搜索仓库时触发 API 速率限制。

### 2. 获取订阅
等待 GitHub Actions 工作流运行结束后，打开仓库根目录中的 `sub.txt` 文件，点击 **Raw** 按钮获取原始数据链接，将其填入您的代理客户端即可使用。

## 文件结构
- `main.py`：负责提取、清洗、去重与生成订阅。
- `discover.py`：负责搜索新仓库并测试有效性。
- `repositories.txt`：节点源仓库白名单。
- `blacklist.txt`：失效仓库黑名单。
- `keyword_stats.json`：搜索行为统计记录。
- `requirements.txt`：Python 依赖列表。
