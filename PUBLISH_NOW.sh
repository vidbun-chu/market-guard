#!/usr/bin/env bash
# ============================================================
# PUBLISH_NOW.sh — 无代理环境下的一键发布
# ============================================================
# 与 publish.sh 的区别：本脚本会先清空代理变量。
# 原因：本机 HTTP_PROXY(54440) 已失效，且该代理未放行 github.com 主站；
#       而 api.github.com 直连可用，因此全程走 API 路径无需代理。
#
# 前置：需要 GH_TOKEN 环境变量（或 ~/.config/gh/hosts.yml 已配好）
# 用法：GH_TOKEN=xxx ./PUBLISH_NOW.sh
# ============================================================
set -euo pipefail

# 关键：清掉失效代理，避免所有请求被黑洞
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export NO_PROXY="*"
export no_proxy="*"

REPO_NAME="market-guard"
cd "$(dirname "$0")"

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; DIM=$'\033[0;2m'; NC=$'\033[0m'
ok(){ echo "${GREEN}✓${NC} $*"; }
die(){ echo "${RED}✗${NC} $*" >&2; exit 1; }
step(){ echo; echo "${DIM}── $* ──${NC}"; }

step "1/5 连通性自检"
CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 12 https://api.github.com)
[ "$CODE" = "200" ] || die "api.github.com 不可达(HTTP $CODE)"
ok "api.github.com 直连正常"

[ -n "${GH_TOKEN:-}" ] || die "请先设置 GH_TOKEN 环境变量"
AUTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 12 \
  -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/user)
[ "$AUTH" = "200" ] || die "token 无效(HTTP $AUTH)"
USER=$(curl -s --max-time 12 -H "Authorization: Bearer $GH_TOKEN" \
  https://api.github.com/user | grep -o '"login":"[^"]*"' | cut -d'"' -f4)
ok "已认证：$USER"

step "2/5 准备远端"
git config user.email "${GIT_EMAIL:-${USER}@users.noreply.github.com}"
git config user.name "${GIT_NAME:-market_guard}"
# 关键：走 API 通道，强制不用代理
git config --global http.proxy ""
git config --global https.proxy ""
ok "git 身份：$USER"

EXISTS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 12 \
  -H "Authorization: Bearer $GH_TOKEN" \
  "https://api.github.com/repos/$USER/$REPO_NAME")

step "3/5 创建仓库"
if [ "$EXISTS" = "200" ]; then
  ok "仓库已存在：https://github.com/$USER/$REPO_NAME"
else
  curl -s --max-time 20 -X POST \
    -H "Authorization: Bearer $GH_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$REPO_NAME\",\"description\":\"账户级风控与趋势工具包：市值止损三轨制 + 大周期定性三问 + 多源容错行情\",\"private\":false,\"has_issues\":true,\"has_wiki\":false}" \
    https://api.github.com/user/repos | grep -q '"id"' \
    || die "创建失败（可能仓库名已被占用，换个名或手动建仓）"
  ok "仓库已创建：https://github.com/$USER/$REPO_NAME"
fi

step "4/5 推送代码与标签"
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$USER/$REPO_NAME.git"
# URL 里嵌 token 避免交互式密码输入（token 只存在于进程内，不落盘）
git push -q -u "https://x-access-token:${GH_TOKEN}@github.com/$USER/$REPO_NAME.git" main \
  || die "推送失败：请确认 token 含 repo 权限"
ok "main 分支已推送"

git push -q "https://x-access-token:${GH_TOKEN}@github.com/$USER/$REPO_NAME.git" --tags \
  || warn "标签推送失败（可稍后补）"
ok "标签已推送：$(git tag | tr '\n' ' ')"

step "5/5 更新 README 徽章"
if grep -q "YOUR_NAME/$REPO_NAME" README.md; then
  sed -i.bak "s|YOUR_NAME/$REPO_NAME|$USER/$REPO_NAME|g" README.md
  rm -f README.md.bak
  git add README.md
  git commit -q -m "docs: 更新徽章指向 $USER"
  git push -q "https://x-access-token:${GH_TOKEN}@github.com/$USER/$REPO_NAME.git" main
  ok "徽章已更新为 $USER"
else
  ok "徽章无需更新"
fi

echo
ok "===== GitHub 完成 ====="
echo "  仓库：https://github.com/$USER/$REPO_NAME"
echo
echo "  下一步（PyPI）："
echo "   1. 打开 https://pypi.org/manage/account/publishing/"
echo "   2. Add publisher → 选 GitHub → 仓库填 $REPO_NAME"
echo "   3. Workflow name 填 publish.yml（必须完全一致）"
echo "   4. 回到仓库 → Releases → Draft a new release → 选 tag v1.0.0 → Publish"
echo "      → 工作流会自动发布到 PyPI"
