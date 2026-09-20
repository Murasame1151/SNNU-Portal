# 发布记录

## v2.1（最新）—— 新增 Linux 支持

| 项目 | 地址 |
| --- | --- |
| 仓库 | https://github.com/Murasame1151/SNNU-Portal |
| Release | https://github.com/Murasame1151/SNNU-Portal/releases/tag/v2.1.0 |

发布内容：

* **Windows**：`CampusNetAutoLogin-v2.1.exe`（12.2 MB）
* **Linux**：`校园网自动认证-linux-x86_64`（13.3 MB，单文件 ELF）
* **Linux 含脚本**：`SNNU-Portal-2.1-linux-x86_64.tar.gz`（13.2 MB）
* 自检：Windows 与 Debian 13（WSL2）双侧 `logictest.py` 全过

## v2.0 —— 图形界面版

<https://github.com/Murasame1151/SNNU-Portal/releases/tag/v2.0.0>

## 敏感信息检查

发布前扫描全部文本文件与二进制，源码中不含任何真实凭据：

| 检查项 | 结果 |
| --- | --- |
| 学号 / 密码明文（源码与二进制） | 未发现 |
| `config.ini` / `secret.bin` / `app.log` | 未提交（`.gitignore` 已排除） |
| `build/`、`__pycache__/`、`_wsl_*.sh` | 未提交 |
| 发布用的 GitHub Token | 用完覆写并删除，从未写入仓库 |

## 后续发版流程

```bash
git add .
git commit -m "feat: ..."
git push origin main
git tag -a v2.2.0 -m "SNNU-Portal v2.2"
git push origin v2.2.0
```

然后在 GitHub 上新建对应 Release，附加：

* Windows：`dist/校园网自动认证.exe`（重命名为 `CampusNetAutoLogin-v2.2.exe`）
* Linux：`dist/校园网自动认证-linux-x86_64`
* Linux 包：`dist/SNNU-Portal-2.2-linux-x86_64.tar.gz`

### Linux 侧构建（在 Debian/Ubuntu 上）

```bash
sudo apt install python3 python3-tk python3-venv
python3 -m venv venv && . venv/bin/activate
pip install pyinstaller requests
./build_linux.sh          # -> dist/校园网自动认证
./build_zipapp.sh         # 或者只打一个几十 KB 的 .pyz
```

> 建议给 GitHub Token 设置到期时间；本次用过的 token 已从磁盘删除，
> 若还没设过期时间，建议到 https://github.com/settings/personal-access-tokens
> 撤销或补上有效期。
