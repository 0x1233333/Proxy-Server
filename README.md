# 🚀 Proxy Nodes Auto Aggregator (自用代理节点聚合器)

> **⚠️ 严正声明 / Disclaimer**
> 
> 本仓库及其包含的所有自动化脚本**仅供个人学习、编程测试及网络环境优化自用**。
> 本人不提供任何节点服务，不存储任何实质性代理服务器，所有数据均由脚本定时从公开的第三方开源 GitHub 仓库中正则提取。请勿将本仓库生成的订阅链接用于任何商业用途或公开分享。使用者因违反相关法律法规造成的任何后果，与本仓库及开发者无关。

---

## ✨ 仓库功能 (Features)

本仓库通过 GitHub Actions 实现了完全无人值守的代理节点抓取与重构工作流，专为配合 Mihomo (Clash Meta) 和 Sing-box 等现代代理核心打造：

- **🔄 定时更新**：每日自动执行一次，同步上游仓库最新变动，确保节点时效性。
- **🛡️ 纯净本地解析 (无惧 API 封锁)**：直接使用 `git clone --depth 1` 拉取上游仓库，在 GitHub Actions 虚拟环境中进行正则扫描与 Base64 智能解码，不依赖不稳定的第三方转换接口。
- **🌐 全协议支持**：支持提取目前主流的绝大多数代理协议，包括但不限于 `vmess`, `vless`, `trojan`, `ss`, `ssr`, `tuic`, `hysteria/hy2`, `wg/wireguard`, `socks5`。
- **🧹 强力去重机制**：剥离节点原有的备注名称，通过对比提取出的核心配置（Host、UUID、端口等）进行 Hash 级去重，彻底解决节点重复搬运问题。
- **🌍 GeoIP 智能重命名**：利用 `ip-api` 接口检测节点真实物理归属地，并将节点标准重命名为 `[国家代码]_[网络层]_[协议]_[序号]` (例如：`US_TCP_VLESS_1`)。
- **📦 标准 Base64 封装**：最终输出标准化的 Base64 订阅文件 `sub.txt`。

---

## 🛠️ 使用方法 (Usage)

### 1. 仓库准备
在你的 GitHub 账号新建一个公开仓库，并上传以下核心文件：
* `repositories.txt`：存放目标仓库链接。
* `requirements.txt`：Python 运行环境依赖。
* `main.py`：核心逻辑脚本。
* `.github/workflows/update.yml`：自动化工作流配置。

### 2. 环境与权限
- **虚拟环境**：GitHub Actions 会自动在 Python 虚拟环境中安装依赖并运行脚本。
- **写入权限**：进入仓库 `Settings` -> `Actions` -> `General` -> `Workflow permissions`，勾选 **`Read and write permissions`** 并保存，否则脚本无法推送更新。

### 3. 获取订阅
运行成功后，访问仓库根目录生成的 `sub.txt`，点击 **Raw** 获取原始链接。将该链接填入代理客户端即可。

---

## 🙏 感谢的上游 (Acknowledgments)

本工具的数据来源包括但不限于以下开源仓库：

* [free-nodes/v2rayfree](https://github.com/free-nodes/v2rayfree)
* [shaoyouvip/free](https://github.com/shaoyouvip/free)
* [Pawdroid/Free-servers](https://github.com/Pawdroid/Free-servers)
* [v2raynnodes/v2rayfree](https://github.com/v2raynnodes/v2rayfree)
* [free-nodes/clashfree](https://github.com/free-nodes/clashfree)
* [clashv2ray-hub/v2rayfree](https://github.com/clashv2ray-hub/v2rayfree)
* [clashv2ray-hub/clashfree](https://github.com/clashv2ray-hub/clashfree)
* [telegeam/freenode](https://github.com/telegeam/freenode)

感谢 [ip-api.com](http://ip-api.com/) 提供的免费地理位置查询服务。
