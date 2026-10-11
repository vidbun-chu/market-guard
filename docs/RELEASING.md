# 发布手册 · GitHub + PyPI

本文档是给**维护者自己**看的操作手册（不是给用户看的使用指南）。

> ### ⚡ 快速路径（推荐）
>
> 装好 `gh` 并登录后，两条命令搞定全部：
>
> ```bash
> ./publish.sh check     # 先跑检查：版本/测试/脱敏/构建/校验
> ./publish.sh repo      # 建 GitHub 仓库 + 推送（顺带把徽章换成你的用户名）
> ./publish.sh release   # 建 Release → 工作流自动发布 PyPI
> ```
>
> 脚本会在每一步做校验并给出可读的中文输出，失败立即中止。
> 下面是这些步骤的手动展开，供理解与排错时参考。

当前状态：**本地全部就绪，GitHub CLI 已安装；仍缺 gh 登录与 PyPI publisher 配置**
（这两步必须你本人操作，见文末"你需要做的"）。

---

## 一、已完成（无需凭证）

- [x] 包结构规范化（`src`-less layout，`pyproject.toml` 驱动）
- [x] `build` + `twine` 工具链安装
- [x] sdist + wheel 构建通过（`market_guard-1.0.0.tar.gz` / `-py3-none-any.whl`）
- [x] 24 个零网络单元测试通过
- [x] Git 仓库初始化 + 首次提交（20 文件，2434 行）
- [x] 版本标签 `v1.0.0`
- [x] CI 工作流（三平台 × Python 3.9–3.13）
- [x] 发布工作流（PyPI OIDC 信任发布）
- [x] Bug 报告模板
- [x] `.gitattributes`（统一 LF，避免 Windows CRLF 污染 PyPI 包）
- [x] 完整脱敏（无真实账户数据、无真实持仓代码）

**包名状态**：`market-guard` 在 PyPI 上未被占用（已核实，可注册）。

---

## 二、GitHub 仓库创建

### 方式 A：一键脚本（★推荐）

```bash
# 前置：安装 gh 并登录
winget install --id GitHub.cli          # 已安装 2.102.0
gh auth login                           # ← 这一步必须你本人操作

# 然后
./publish.sh repo                       # 建仓 + 推送 + 更新徽章，一条命令
```

脚本会自动：
- 检测 `gh` 是否登录，未登录直接报错退出
- 仓库已存在则跳过创建，直接推送（可重复执行，幂等）
- 推送 `main` 分支与全部 tag
- 把 README 徽章里的 `YOUR_NAME` 替换成你的真实用户名并再推一次

### 方式 B：手动网页

1. 打开 <https://github.com/new>
2. Repository name：`market-guard`
3. Description：`账户级风控与趋势工具包：市值止损三轨制 + 大周期定性三问 + 多源容错行情`
4. **Public**（要发 PyPI 必须公开）
5. ⚠️ **不要勾选** "Add a README file" / "Add .gitignore" / "Choose a license"
   —— 本地已有，勾了会冲突
6. Create repository

然后在本地推送：

```bash
cd /c/Users/bin/WorkBuddy/Claw/packages/market_guard
git remote add origin https://github.com/<你的用户名>/market-guard.git
git push -u origin main
git push origin v1.0.0
```

> Windows 上 `gh` 装完可能需要重开终端，或临时加 PATH：
> `export PATH="$PATH:/c/Program Files/GitHub CLI"`

### 方式 C：装 gh CLI

```powershell
winget install --id GitHub.cli
gh auth login
gh repo create market-guard --public --source=. --remote=origin --push
gh repo edit --enable-issues=true
```

---

## 三、PyPI 发布（两种方式，择一）

### 方式 A：OIDC 信任发布（★推荐，仓库零 Token）

**一次性配置**（约 5 分钟，**必须你本人操作**）：

1. 登录 <https://pypi.org/manage/account/publishing/> → "Add a new publisher"
2. 选择 **GitHub**（不要选 token）
3. 填写：
   - Organization / User：`你的GitHub用户名`
   - Repository name：`market-guard`
   - Workflow name：`publish.yml`  ← **必须与工作流文件名一致**
4. Save

**每次发版**：

```bash
# 1. 改版本号（pyproject.toml 的 version + market_guard/__init__.py 的 __version__）
# 2. 提交并打 tag
git add -A && git commit -m "release: v1.0.1"
git tag -a v1.0.1 -m "v1.0.1"
git push origin main --tags

# 3. 或直接用脚本，它会检查版本一致性并建 Release
./publish.sh release
```

> 为什么推荐这个：仓库里**不需要存任何 API Token**，泄露风险归零，
> 且 PyPI 会对每次上传做来源验证。

### 方式 B：本地 API Token

```bash
# 1. 到 https://pypi.org/manage/account/token/ 创建 token
#    选 "pypi.org" 上传范围 → 给个名字 → 复制 token（只显示一次）

# 2. 配置 ~/.pypirc（Windows: %USERPROFILE%\.pypirc）
cat > ~/.pypirc <<'EOF'
[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmcxxxxxxxxxxxxxx
EOF

# 3. 先 dry-run 检查
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*    # 先传测试站

# 4. 正式上传
python -m twine upload dist/*
```

> ⚠️ Token 不要提交进 git。`.gitignore` 已忽略 `.pypirc` 之外的情况，
> 但请务必确认 `~/.pypirc` 在仓库外（默认就在用户目录，不会被提交）。

---

## 四、发版检查清单

**用脚本**（推荐，一次跑完 6 项）：

```bash
./publish.sh check
```

**手动核对**（脚本失败时排查用）：

```bash
# 1. 版本号三处一致
grep '^version' pyproject.toml
grep '__version__' market_guard/__init__.py
git tag -l

# 2. 测试通过
python tests/test_core.py

# 3. 干净构建
rm -rf dist build *.egg-info && python -m build

# 4. 元数据校验（必须无 error）
python -m twine check dist/*

# 5. 包内容正确（不该含测试/缓存/真实数据）
python -m zipfile -l dist/*.whl | head -20
tar tzf dist/*.tar.gz | grep -E "test|__pycache__|\.pyc"

# 6. 无敏感信息泄漏
grep -rniE "password|token|secret|api_key" \
  --include="*.py" --include="*.md" --include="*.json" . | grep -v CHANGELOG
```

> ⚠️ 产物文件名注意：现代 setuptools 会把 `market-guard` 规范化成
> `market_guard-1.0.0-py3-none-any.whl`（下划线）。
> 脚本已用通配符匹配，两种命名都能识别。

---

## 五、常见问题

**Q: twine upload 报 409 / 文件已存在？**
PyPI 不允许重复上传同名文件。必须提升版本号（1.0.0 → 1.0.1），
即使内容完全相同。

**Q: `twine check` 报 `SetuptoolsDeprecationWarning`？**
`pyproject.toml` 里同时写了 `license = "MIT"` 和旧的 License classifier。
已在本项目修复为只用 SPDX 表达（`license = "MIT"` + `license-files`）。

**Q: 包名冲突？**
PyPI 包名大小写不敏感，`market-guard` 和 `market_guard` 视为同一个。
本项目包名用连字符 `market-guard`（PyPI 惯例），导入名用下划线 `market_guard`。

**Q: Windows 上打出来的包有 CRLF 怎么办？**
已在 `.gitattributes` 统一 `eol=lf`。构建产物本身在 Linux CI 上生成，
不会有问题。

**Q: 想在 README 徽章里显示真实 GitHub 用户名？**
把 README 中 `YOUR_NAME` 替换为你的实际用户名。

---

## 六、发布后验证

```bash
# 1. PyPI 页面
open https://pypi.org/project/market-guard/

# 2. 全新环境安装测试
pip install market-guard
python -m market_guard demo

# 3. 检查元数据完整性
python -c "from importlib.metadata import metadata; \
  m=metadata('market-guard'); \
  print('版本:', m['Version']); \
  print('许可:', m.get('License-Expression')); \
  print('依赖:', m.get_all('Requires-Dist') or '无（零依赖）')"
```

若在 PyPI 页面看到 `Requires: 0` 是正确的——这是本项目最大的卖点。

---

## 相关链接

- PyPI 项目页：<https://pypi.org/project/market-guard/>
- PyPI 打包指南：<https://packaging.python.org/>
- OIDC 信任发布：<https://pypi.org/manage/account/publishing/>
- GitHub Actions 发布：<https://github.com/pypa/gh-action-pypi-publish>
