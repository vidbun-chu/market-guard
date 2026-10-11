#!/usr/bin/env bash
# ============================================================
# publish.sh — market_guard 一键发布到 GitHub + PyPI
# ============================================================
# 前置条件：
#   1. 已安装 gh 并完成 `gh auth login`
#   2. 已在 PyPI 配置好 OIDC 信任发布（publisher 指向本仓库）
#      或已配置 ~/.pypirc 的 API Token
#
# 用法：
#   ./publish.sh check      仅做发布前检查，不推送
#   ./publish.sh repo       创建 GitHub 仓库并推送（含 tag）
#   ./publish.sh pypi       本地上传 PyPI（需 token）
#   ./publish.sh release    打 tag + 建 GitHub Release，触发 OIDC 自动发布
#   ./publish.sh all        依次执行 repo → release
# ============================================================
set -euo pipefail

REPO_NAME="market-guard"
PKG_NAME="market-guard"
PY="python"
cd "$(dirname "$0")"

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; DIM=$'\033[0;2m'; NC=$'\033[0m'
ok()   { echo "${GREEN}✓${NC} $*"; }
warn() { echo "${YELLOW}!${NC} $*"; }
die()  { echo "${RED}✗${NC} $*" >&2; exit 1; }
step() { echo; echo "${DIM}── $* ──${NC}"; }

# ------------------------------------------------------------
step "1/6 版本一致性"
VER_PYPROJECT=$(grep -oP '(?<=^version = ")[^"]+' pyproject.toml)
VER_CODE=$(grep -oP '(?<=__version__ = ")[^"]+' market_guard/__init__.py)
TAGS=$(git tag -l | tr '\n' ' ')

echo "  pyproject.toml : $VER_PYPROJECT"
echo "  __init__.py    : $VER_CODE"
echo "  git tags       : ${TAGS:-（无）}"
[ "$VER_PYPROJECT" = "$VER_CODE" ] || die "版本号不一致，pyproject 与 __init__ 必须相同"
ok "版本号一致：$VER_PYPROJECT"

# ------------------------------------------------------------
step "2/6 单元测试"
"$PY" tests/test_core.py | tail -1
ok "测试通过"

# ------------------------------------------------------------
step "3/6 脱敏与敏感信息检查"
LEAK=$(grep -rniE "password|secret|api[_-]?key|ghp_|github_pat_|BEGIN RSA|sk-[a-zA-Z0-9]{16}" \
  --include="*.py" --include="*.json" --include="*.toml" . 2>/dev/null \
  | grep -viE "token|示例|文档|见 |请 |无需|不要" || true)
[ -z "$LEAK" ] || { echo "$LEAK"; die "检测到疑似真实密钥"; }
ok "无密钥泄漏"

# 只匹配真正的待办标记（带冒号/括号形式），避免 xxxxxx 占位符与
# "XXX_" 之类的说明文字被误判。锚定在行首注释或代码上下文。
PRIVATE=$(grep -rnE "(^|[[:space:]])(TODO|FIXME|HACK)([:：[:space:]]|$)" \
  --include="*.py" --include="*.toml" . 2>/dev/null || true)
[ -z "$PRIVATE" ] || warn "有待办标记（不阻塞发布）："
[ -z "$PRIVATE" ] || echo "$PRIVATE" | head -5

# ------------------------------------------------------------
step "4/6 构建分发包"
rm -rf dist build *.egg-info
"$PY" -m build 2>&1 | tail -3

# 注意：现代 setuptools 会把产物文件名规范化为下划线
#（market_guard-1.0.0.whl），而非 pyproject 里的连字符名。
# 因此这里用通配符匹配，不硬编码分隔符。
WHL=$(ls dist/*"-${VER_PYPROJECT}-py3-none-any.whl" 2>/dev/null | head -1 || true)
SDIST=$(ls dist/*"-${VER_PYPROJECT}.tar.gz" 2>/dev/null | head -1 || true)

[ -n "$WHL" ]   || { echo "dist/ 内容："; ls dist/ 2>/dev/null; die "wheel 构建产物缺失"; }
[ -n "$SDIST" ] || { echo "dist/ 内容："; ls dist/ 2>/dev/null; die "sdist 构建产物缺失"; }
ok "构建完成：$(ls dist/ | tr '\n' ' ')"

"$PY" -m twine check dist/* || die "twine check 未通过"
ok "元数据校验通过"

# ------------------------------------------------------------
step "5/6 工作区状态"
if [ -n "$(git status --porcelain)" ]; then
  warn "有未提交改动："
  git status --short
  die "请先提交后重试"
fi
ok "工作区干净"

CMD="${1:-check}"

case "$CMD" in
  check)
    echo
    ok "===== 检查通过，可执行下一步 ====="
    echo "  ./publish.sh repo     创建 GitHub 仓库并推送"
    echo "  ./publish.sh release  打 Release 触发 PyPI 自动发布"
    ;;

  repo)
    step "创建 GitHub 仓库"
    command -v gh >/dev/null || die "未安装 gh，请先执行: winget install --id GitHub.cli"
    gh auth status >/dev/null || die "gh 未登录，请先执行: gh auth login"
    ok "gh 已登录：$(gh api user -q .login)"

    USER=$(gh api user -q .login)
    if gh repo view "$USER/$REPO_NAME" >/dev/null 2>&1; then
      warn "远程仓库已存在，改为直接推送"
    else
      gh repo create "$REPO_NAME" --public \
        --description "账户级风控与趋势工具包：市值止损三轨制 + 大周期定性三问 + 多源容错行情" \
        --source=. --remote=origin
      ok "仓库已创建：https://github.com/$USER/$REPO_NAME"
    fi

    git push -u origin main
    git push origin --tags
    ok "代码与 tag 已推送"

    # 顺手把 README 里的 YOUR_NAME 换成真实用户名
    if grep -q "YOUR_NAME/$REPO_NAME" README.md; then
      sed -i.bak "s|YOUR_NAME/$REPO_NAME|$USER/$REPO_NAME|g" README.md
      rm -f README.md.bak
      git add README.md
      git commit -q -m "docs: 更新徽章指向真实 GitHub 用户名 ($USER)"
      git push -q origin main
      ok "README 徽章已更新为 $USER"
    fi
    ;;

  release)
    step "创建 Release（触发 PyPI OIDC 自动发布）"
    command -v gh >/dev/null || die "未安装 gh"
    gh auth status >/dev/null || die "gh 未登录"
    git push origin main --tags || die "推送失败"
    gh release create "v$VER_PYPROJECT" \
      --title "market_guard $VER_PYPROJECT" \
      --generate-notes
    ok "Release 已创建，工作流将自动上传 PyPI"
    echo "  观察进度: gh run watch"
    ;;

  pypi)
    step "本地上传 PyPI（需 token）"
    "$PY" -m twine upload dist/*
    ok "上传完成：https://pypi.org/project/$PKG_NAME/"
    ;;

  all)
    "$0" repo && "$0" release
    ;;

  *)
    die "未知命令：$CMD（可选 check / repo / release / pypi / all）"
    ;;
esac
