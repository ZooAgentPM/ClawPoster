---
name: visual-rag-design
description: 负责所有设计物料的出图全流程——包括但不限于：海报、封面、配图、邀请函、宣传图、活动图、朋友圈图、小红书封面/配图、公众号配图、品牌物料等。只要涉及「出图」「做图」「生成图片」「设计」类需求，均使用此技能。通过 visual-rag MCP 服务直接生成 PNG 图片，图片实时返回对话，无需管理文件或服务。
---

# **虾稿设计**

MCP 服务地址：`https://syncopated-retractively-anitra.ngrok-free.dev/mcp`
若工具不可用或域名失效，告知用户联系****小邹****获取新地址。

---

## **⚠️ Agent 必读：文案决定这张图值不值得发出去**

> ****不能用模板默认值填槽位，不能自己编造内容，不能让用户选模板。****

### **为什么？**

模板的槽位是空容器，填什么决定图的质量。Agent 的默认行为是用占位符或泛化文字填充——这会产生一张格式正确但内容无效的图。选模板也是 Agent 的职责，不是用户的负担。

### **出图工作流（必须遵循）**

| 步骤 | 做什么 | 关键约束 |
|------|--------|---------|
| 0. 启动状态页 | 创建任务，获取播报链接 | 第一件事，不可跳过 |
| 1. ensure_services | 确认服务就绪 | 失败则停止，告知用户 |
| 2. search_templates | 语义搜索候选模板 | query 必须含受众/主张/风格 |
| 3. 选择模板 | 自主选出最优一个 | 不展示候选让用户选，不动用户的手 |
| 4. get_template_spec | 读取槽位规格 | template_id 纯整数，不带 t |
| 5. 填写槽位 | 写文案，填内容 | must_edit 必须追问用户，不能编造 |
| 6. generate_poster | 渲染出图 | slots 是字典格式 |
| 7. 验收 | 质检 + 目视确认 | 🔴必处理，通过后上报 done |

### **常犯错误**

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 用「您的标题」「示例文字」填槽位 | 追问用户获取真实内容，或用文案方法论从已有内容提炼 |
| 展示候选模板让用户选 | Agent 自主选最优，直接进下一步 |
| search query 只写「封面图」 | query 含格式+受众+主张+情绪，见 Step 2 格式 |
| template_id 写成 "t148" | 纯整数：148 |
| 质检报告是🟡就跳过 | 调用 get_slot_crops 放大确认后再决定 |
| 验收通过后额外回复用户 | 上报 done，状态页自动展示结果，不再说话 |
| 直接 curl port 7002 创建状态页 | 必须走 port 3000，否则 task_id 绑定失败 |

---

## **实战案例**

以下均为真实跑出，记录的是工具调用序列和关键决策点。

---

### **实战成功案例：5 分钟完成「攒钱小白」封面（含整批放弃重搜）**

```
1. search_templates → query="理财 存钱 女性", n=8
   返回：
     t418 牛皮纸拼贴复古风       →  ❌ 情感/收藏调，无实操承托力
     t910 双十一购物备忘录       →  ❌ 场景错位
     t870 金融热词权威风         →  ❌ 权威感压小白受众
     t604 618美妆促销粉色系      →  ❌ 内容完全无关
     t578 五一旅行拼贴           →  ❌ 内容完全无关
     t359 数据图表金融报告       →  ❌ 过于专业抽象，抬高受众门槛
     t639 手绘插画心理学毛笔字   →  ❌ 轻巧感，无实操承托力
     t580 手绘插画宅家贴纸风     →  ❌ 轻巧感，无实操承托力
   → 整批无一能承托「我教你一个具体省钱方法」的实操感，整批放弃

2. search_templates → query="省钱 指南 实操 小白 方法"
                      exclude="古风 国风 水墨 手绘 插画 促销 喜庆 表情包"
   返回 t417（纯黄色底+六边形白框+超大 hero_text，密度 light）  →  ✅

3. get_template_spec(417) →
   主标题 uuid-d479: max_per_line=3, line_break=true, must_edit=true
   tagline uuid-6c4d: max_per_line=10, must_edit=true

4. 读 references/copy-xhs-cover.md → 诊断：
   内容形态=指南型，受众动机=实用 → 结构E（指南承诺）
   核心词=「攒钱」（受众内部语言，不用「理财」）先出

5. generate_poster(417, {"uuid-d479": "攒钱\n小白\n必看", "uuid-6c4d": "方法超简单！"})
   → 质检 🟡（hero_text 超大字撑满容器）→ get_slot_crops 确认 → ✅ 通过
```

****关键决策点：****
- 看到 t359 图表风「相对最接近」→ 错的气质=错的图，不将就 → 整批放弃
- 看到第一批全是情感/促销/手绘 → exclude 填风格词（向量方向排斥，不是关键词过滤）→ 重搜方向彻底不同
- 🟡 出现在 hero_text 模板 → 超大字撑满容器是正常状态 → get_slot_crops 目视确认后放行

---

### **实战成功案例：内容丰富 → 主动读参考文案 → 推导核心词出图（AI副业封面）**

```
1. 用户提供长段内容 → 填槽前先读 references/copy-xhs-cover.md 做诊断

2. 文案诊断 →
   内容形态：观点型（「大家都搞错了方向」= 反常识论点，不是步骤/发现/情感）
   受众动机：身份焦虑（「大家都在追工具」→ 读者对号入座「我也是那个追工具的人吗？」）
   → 选结构B（悬念缺口）：已知行为先出，反转结论后出

3. 核心词推导 →
   候选：AI副业 / 工具 / 赚钱 / 需求
   AI副业 = 受众搜索入口词，焦虑触发点              →  ✅ 先出
   工具/赚钱 = 内容论点，读者还不认可，不能先出      →  ❌
   信息顺序：AI副业（已知）→ 你搞错（危机）→ 方向了（悬念）

4. search_templates → query="AI 副业 赚钱 认知 观点 反差"
   选 t553（浏览器框 hacker 字体极简白底）
   浏览器框=网感，极简白底=观点文字零干扰  →  ✅ 与「反常识论点」气质匹配

5. generate_poster(553, {主标题: "AI副业\n你搞错\n方向了\n根本原因"})
   → 质检 🔴：scrollH=1365 > clientH=1025，4行撑爆容器

6. 分析：max_per_line=5 在限内，但行数>容器物理高度 → 减行保核心->文字排版要错落有致
   generate_poster(553, {主标题: "AI副业\n你搞错方\n向了"})
   → 质检 🟡 → get_slot_crops 确认 → ✅ 通过
```

****关键决策点：****
- 看到内容是「反常识论点」→ 内容形态=观点型 → 不选指南/发现结构
- 4个核心词候选 → 只有「AI副业」是受众焦虑入口词，其余都是论点 → 论点不能先出
- 🔴 出现，scrollH > clientH → 原因=行数超容器高度（不是字数问题）→ 减行不改文意

---

## **流程鸟瞰**

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐
│ 启动状态页 │─▶│ 搜索模板  │─▶│ 选择模板  │─▶│ 读取规格  │─▶│ 填写文案  │─▶│ 生成图片  │─▶│ 验收 │
└──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────┘
   第一件事      语义优先      自主决策        纯整数ID      方法论驱动     slots=字典     三色质检
```

---

## **状态页协议**

****默认开启。**** 用户说「不用播报」「静默」「安静做就行」时跳过。

### **启动（收到任务后第一件事）**

```bash
RESULT=$(**curl** -s -X POST http://127.0.0.1:3000/status/create \
  -H "Content-Type: application/json" -d '{"agent_id":"contentcreater"}')
**TASK_ID**=$(**echo** "$RESULT" | **python3** -c "import sys,json; print(json.load(sys.stdin)['task_id'])")
STATUS_PATH=$(**echo** "$RESULT" | **python3** -c "import sys,json; print(json.load(sys.stdin)['status_url'])")

PROGRESS_FILE="$HOME/.openclaw/workspace/memory/progress-${TASK_ID}.md"
**echo** "收到！进度实时更新：https://syncopated-retractively-anitra.ngrok-free.dev${STATUS_PATH}" > "$PROGRESS_FILE"

CRON_ID=$(**bash** {skill_dir}/scripts/start_broadcast.sh \
  "{deliveryContext.to}" "{deliveryContext.account_id}" \
  "$PROGRESS_FILE" "{deliveryContext.channel}" "30s")
```

### **执行过程**

MCP 工具（ensure_services / search_templates / get_template_spec / generate_poster / get_slot_crops）执行完后****自动****向状态页推送进度，无需手动上报。专注出图流程即可。

### **完成时**

```bash
*# 1. 标记状态页完成*
**curl** -s -X POST "http://127.0.0.1:3000/status/${TASK_ID}/update" \
  -H "Content-Type: application/json" \
  -d '{"step":"done","message":"出炉了！热乎的 🎉","data":{"render_url":"<render公网URL>"}}'

*# 2. 清理*
**openclaw** cron rm "$CRON_ID"
**rm** -f "$PROGRESS_FILE" "${PROGRESS_FILE}.sent"
```

状态页自动停止轮询，展示 render 大图。****不需要额外回复用户。****

---

## **Step 1：ensure_services**

---

## **Step 2：搜索模板**

```
search_templates(query, usage_type="cover", n=8, include_thumbnails=True, exclude="")
```

****Query 格式：****
```
格式:[cover/content/poster] 语义:[为{目标受众}做{格式}，传达{核心主张}，整体{情绪/风格}]
```

****搜索策略决策树：****
```
返回结果相关？
  → ✅ 进入 Step 3 选择
  → ❌ 风格偏 → 加 exclude 参数重搜
       仍无结果 → list_templates(keyword) 兜底
```

****负向排除（风格不对时）：****
```
search_templates(query="...", exclude="古风 国风 水墨 手绘", n=8)
```
`exclude` 是向量方向排斥，不是关键词过滤，填风格词即可。

---

## **Step 3：选择模板**

从返回的候选中****自主****选出最优一个，不展示候选、不询问用户。

`search_templates` 默认返回缩略图合图（`include_thumbnails=true`），直接目视判断模板视觉风格是否与内容气质匹配，不要只看文字描述。

****选择优先级：****
```
1. 内容形态匹配（cover/content/poster 对得上）
2. 情绪/风格吻合（缩略图目视 + query 中情绪词一致）
3. 槽位密度适配（内容多选高密度模板）
```

****选不出来时：****
```
全部不匹配 → 调整 query 或加 exclude 重搜，不打扰用户
重搜仍无 → 告知用户暂无合适模板，请提供更多信息
```

---

## **Step 4：get_template_spec**

```
get_template_spec(template_id)   # 纯整数，不带 t 前缀
```

---

## **Step 5：填写槽位内容**

****格式约束：****
- `list_line_count: N` → 必须填满恰好 N 条
- `max_per_line` → 每行字数绝对不超过
- `line_break: true` → 手动加 `\n`；单个语义单元内被迫拆行时，要有自动换行的感觉——读者感知到的是「这行放不下了，续到下一行」，而不是「这是新的一句话」
- `must_edit: true` → 必须填，其余保留原值

****内容来源决策树：****
```
用户已提供该字段内容？
  → ✅ 直接使用，按格式约束裁剪
  → ❌ must_edit: true → 停下来追问用户，不能编造
       must_edit: false → 保留模板默认值
```

****标题/文案类槽位：**** 读取 `references/copy-xhs-cover.md` 应用文案方法论。

---

## **Step 6：generate_poster**

```
generate_poster(template_id, slots, adjustments?)
```

⚠ `slots` 是字典：`{"uuid": "填入文字"}`

---

## **Step 7：验收**

****质检决策树：****
```
读质检报告
  🔴 → 必须处理，重新填槽位或调整后重渲
  🟡 → 调用 get_slot_crops 放大确认
        确认无问题 → ✅
        有问题     → 按 🔴 处理
  ✅ → WebFetch 看 render URL 目视确认
        文字通顺？占位符残留？空白？
        有布局问题 → 用 inspect URL 定位，带 adjustments 重渲
        通过       → 上报 done，不再额外回复用户
```

---

## **Step 8：交付**

验收通过后：
1. 将 render 图**直接展示给用户**（图片预览，不只是发链接）
2. 告知下载地址——**必须用响应返回的「下载render」链接原文，不得自行拼接文件名**

也可将 base64 解码存为本地文件（不依赖下载链接）：
```python
import base64
with open("poster.png", "wb") as f:
    f.write(base64.b64decode("<响应 data 字段>"))
```

---

## **进阶：批量生成（3张以上）**

****主 Agent 持有唯一 cron，子 Agent 只负责生图并回传。****

### **主 Agent 职责**

1. 创建进度文件：

```
---
status: running
task_id: {task_id}
mode: batch
total: {N}
done: 0
---
收到！共 {N} 张图，并行生成中，完成一张就告诉你 🚀
```

2. 启动一个 cron：

```bash
**bash** {skill_dir}/scripts/start_broadcast.sh \
  {task_id} {to} {account_id} \
  ~/.openclaw/workspace-{agent_id}/memory/progress-{task_id}.md \
  {interval} {channel}
```

3. 并行启动 N 个子 Agent，等待回传
4. 每收到回传 → done +1，追加 render_url 到进度文件
5. 全部完成 → 写 status=done

### **进度文件正文格式**

```
已完成 {done}/{total}

✅ 第1张 [主题A]
→ {render_url}

⏳ 第2张 生成中...
```

### **子 Agent 回传格式**

子 Agent ****不创建 cron、不写进度文件****，只做完整生图流程（Step 1~7），完成后回传：

```
第N张 [主题] ✅/⚠️
render: [render_url]
模板: t[ID]
问题: [无 / 具体描述]
```

---

## **常见陷阱**

| 陷阱 | 表现 | 解决 |
|------|------|------|
| 状态页走了 port 7002 | task_id 无法绑定 session，状态页空白 | 必须 POST port 3000/status/create |
| template_id 带 t 前缀 | 工具报错找不到模板 | 纯整数：148，不是 t148 |
| slots 传了列表而非字典 | 渲染失败 | `{"uuid": "文字"}`，不是 `["文字"]` |
| must_edit 槽位自行编造 | 图上信息错误，用户无法使用 | 停下来追问用户 |
| 展示候选模板给用户选 | 违背产品原则，用户要动手 | Agent 自主决策，直接进下一步 |
| 质检🟡直接放行 | 文字溢出/截断未被发现 | 调 get_slot_crops 放大确认 |
| 行数太多导致🔴 | max_per_line 在限内但容器高度不够 | 减行数，不要死守字数上限填满每行 |
| query 只写类目词 | 核心词没进 query，搜不到对的模板 | 把核心词本身写进 query（邪修/简历/攒钱…）|
| 槽位填 `/` 字符 | palxp 渲染器截断，图上 `/` 消失 | 用全角 `／` 或改写表达绕开 |
| 搜索结果风格偏差仍将就用 | 勉强选了不匹配的模板，图出来气质全错 | 整批放弃，加 exclude 重搜，不挑"相对最好的" |
| 验收后额外回复用户 | 用户收到重复消息 | 上报 done 即止，状态页自动展示 |
| render URL 用本地地址或自行拼接文件名 | 用户打开是旧图或 404（石小泽案例） | 下载地址必须用响应返回的链接原文，不得自行构造 |

---

## **参考文件**

按图片类型读取对应文案方法论：

- `references/copy-xhs-cover.md` — 小红书封面 / 社媒封面标题

---

## **原则**

- 内容多换高密度模板，不删减用户内容
- render URL 通过 cron 发给用户，不自行构造路径

