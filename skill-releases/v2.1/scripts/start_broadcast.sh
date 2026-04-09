#!/bin/bash
# 启动进度播报 cron
# 用法: start_broadcast.sh <task_id> <to> <account_id> <progress_file> <interval> [channel]
#
# contentcreater 只需正常写进度文件，无需维护任何版本字段
# 去重逻辑完全由本脚本生成的 check 脚本负责

TASK_ID="$1"
TO="$2"
ACCOUNT_ID="$3"
PROGRESS_FILE="$4"
INTERVAL="${5:-20s}"
CHANNEL="${6:-feishu}"

if [ -z "$TASK_ID" ] || [ -z "$TO" ] || [ -z "$ACCOUNT_ID" ] || [ -z "$PROGRESS_FILE" ]; then
  echo "用法: $0 <task_id> <to> <account_id> <progress_file> <interval> [channel]" >&2
  exit 1
fi

SCRIPT_DIR=$(dirname "$PROGRESS_FILE")
CHECK_SCRIPT="${SCRIPT_DIR}/check_${TASK_ID}.py"
HASH_FILE="${SCRIPT_DIR}/sent_hash_${TASK_ID}.txt"
INIT_ID_FILE="${SCRIPT_DIR}/init_id_${TASK_ID}.txt"
CLEANUP_SCRIPT="${SCRIPT_DIR}/cleanup_${TASK_ID}.sh"

# check 脚本：读 body hash，contentcreater 零负担
cat > "$CHECK_SCRIPT" << PYEOF
import sys, hashlib

progress_file = sys.argv[1]
hash_file = sys.argv[2]

try:
    content = open(progress_file).read()
except FileNotFoundError:
    print('missing')
    sys.exit(0)

# 提取正文（第二个 --- 之后）
parts = content.split('---', 2)
body = parts[2].strip() if len(parts) >= 3 else content.strip()
current_hash = hashlib.md5(body.encode()).hexdigest()

try:
    last_hash = open(hash_file).read().strip()
except FileNotFoundError:
    last_hash = ''

if current_hash != last_hash:
    open(hash_file, 'w').write(current_hash)
    print('new')
else:
    print('old')
PYEOF

# ── 主 cron 消息 ──────────────────────────────────────────────
MAIN_MESSAGE="执行以下步骤，只输出最终回复内容，不加任何解释。

步骤一：读文件 ${PROGRESS_FILE}
若文件不存在 → 你的回复是 NO_REPLY，结束。

步骤二：检查文件头部 status 字段
若值为 done 或 failed：
  把文件中第二个 --- 之后的全部内容原样作为回复，不加任何前缀；
  执行 bash ${CLEANUP_SCRIPT}；结束。

步骤三：执行命令 python3 ${CHECK_SCRIPT} ${PROGRESS_FILE} ${HASH_FILE}
- 输出 new → 把文件中第二个 --- 之后的全部内容原样作为回复，不加任何前缀
- 输出 old → 你的回复是 NO_REPLY"

CRON_OUTPUT=$(openclaw cron add \
  --name "progress-${TASK_ID}" \
  --every "$INTERVAL" \
  --session isolated \
  --message "$MAIN_MESSAGE" \
  --announce \
  --channel "$CHANNEL" \
  --to "$TO" \
  --account "$ACCOUNT_ID" \
  --json 2>&1)

CRON_ID=$(echo "$CRON_OUTPUT" | python3 -c "
import sys, json, re
text = sys.stdin.read()
m = re.search(r'\{.*\}', text, re.DOTALL)
if m:
    try:
        data = json.loads(m.group(0))
        print(data.get('id', ''))
    except Exception:
        pass
" 2>/dev/null)

if [ -z "$CRON_ID" ]; then
  echo "ERROR: 创建 cron 失败: $CRON_OUTPUT" >&2
  exit 1
fi

# cleanup 脚本：cron_id 硬编码，agent 一条命令搞定清理
cat > "$CLEANUP_SCRIPT" << CLEANEOF
#!/bin/bash
openclaw cron rm ${CRON_ID}
rm -f ${PROGRESS_FILE} ${CHECK_SCRIPT} ${HASH_FILE} ${INIT_ID_FILE} ${CLEANUP_SCRIPT}
CLEANEOF
chmod +x "$CLEANUP_SCRIPT"

# 把 cron_id 写回进度文件
if [ -f "$PROGRESS_FILE" ]; then
  sed -i '' "s/^cron_id:.*/cron_id: ${CRON_ID}/" "$PROGRESS_FILE"
fi

# ── 初始 cron：15s 后立即发一条俏皮开场白，然后自删 ─────────────
INIT_MESSAGE="执行以下步骤，只输出最终回复内容，不加任何解释。

步骤一：随机生成一句俏皮的开场白，围绕「AI 图片设计任务刚刚启动、正在全速运行」这个场景，语气活泼自然，结尾带合适的 emoji，不超过 25 字，每次都不同。把这句话作为你的回复输出。

步骤二：读取文件 ${INIT_ID_FILE} 获取 init_cron_id，执行 openclaw cron rm <init_cron_id 的值>，然后执行 rm -f ${INIT_ID_FILE}。"

INIT_OUTPUT=$(openclaw cron add \
  --name "init-${TASK_ID}" \
  --every "15s" \
  --session isolated \
  --message "$INIT_MESSAGE" \
  --announce \
  --channel "$CHANNEL" \
  --to "$TO" \
  --account "$ACCOUNT_ID" \
  --json 2>&1)

INIT_ID=$(echo "$INIT_OUTPUT" | python3 -c "
import sys, json, re
text = sys.stdin.read()
m = re.search(r'\{.*\}', text, re.DOTALL)
if m:
    try:
        data = json.loads(m.group(0))
        print(data.get('id', ''))
    except Exception:
        pass
" 2>/dev/null)

if [ -n "$INIT_ID" ]; then
  echo "$INIT_ID" > "$INIT_ID_FILE"
else
  echo "WARN: 创建 init cron 失败: $INIT_OUTPUT" >&2
fi

echo "$CRON_ID"
