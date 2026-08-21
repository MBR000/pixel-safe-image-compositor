# pixel-safe-image-compositor

[English](README.md) | 简体中文

让视觉 AI 负责构图与背景创意——但绝不允许它触碰受保护的像素。
AI 负责规划和绘制；程序负责恢复和校验。

这是一个 Codex / Agent skill，用于这样的图像合成场景：最终图像中的受保护源区域
（产品抠图、人物、艺术品）必须**逐像素一致**地保留。视觉 AI 决定版式、背景和
过渡创意；确定性脚本在生成前校验 mask 几何形状，在生成后恢复受保护像素并用
SHA-256 校验。AI 渲染结果永远不会被当作源图保真的证明。

## 为什么需要它

图像模型总喜欢"优化"你贴进去的内容：logo 被重绘、标签被重新排版、人脸发生漂移。
如果你的场景要求源区域可证明地保持原样（电商、品牌素材、档案资料），仅靠 prompt
无法提供保证。这个 skill 把保证写进了代码：

- **预检门禁（Preflight gate）**——在任何生成之前校验 mask 几何形状。
  不合格的形状（矩形、长直边、连续闭合轮廓）会以退出码 1 终止流水线，
  而不是产出一张糟糕的图。
- **程序化恢复（Programmatic restore）**——只把非透明的源像素以整数偏移
  贴回原位。不缩放、不旋转、不做透视变换。
- **密码学校验（Cryptographic verification）**——最终 PNG 从磁盘重新读取，
  用 SHA-256 比对受保护像素。任何不匹配都会得到 `verified=false` 和非零退出码。

## 功能特性

- 四种合成模式：
  - `photo_echo`——zine 版式：照片满幅出血贴到画布边缘，只有一条沿内容线
    （地平线、山脊）走的有机撕缝，缝外的插画层重绘照片自身的元素——
    "纸上撕开一个连续世界"的最强读感
  - `subject_cutout`——干净抠图主体置于设计好的画面场域中
  - `organic_context`——主体融入有机插画场景
  - `photo_window`——显式的矩形照片窗口（唯一允许矩形 mask 的模式）
- 对包含地平线、山脊、桌沿、屋顶线或人物动作线的完整照片，默认使用
  `photo_echo`，通过 `scripts/build_photo_echo_mask.py` 生成开放式满幅撕缝，
  不要先把照片包进闭合的有机 blob。
- 有机模式下的硬性几何限制，全部由代码强制执行：
  - 禁止矩形 / 圆角矩形 / 规则撕边
  - 禁止"视觉矩形"：结合矩形度（rectangularity）、四角占用率（corner
    occupancy）和边缘平均内缩量的感知门禁，能拦截边缘抖动但整体仍读作
    矩形的形状
  - 连续直边不得超过受保护区域最长边的约 12%（水平、垂直、对角线都会测量）
  - 任意角度的近直线段不得超过约 15%（容差弦拟合能捕捉浅斜线和抖动长边）
  - 禁止等距尖刺或规则锯齿（通过对每条轮廓做周期性锯齿分析检测，而非自我申报）
  - 边界必须在大 / 中 / 小三个尺度上都有变化
  - 受保护边缘外必须有安静的纸面缓冲区
  - AI 过渡形状必须是分离的、局部开放的形状——绝不允许闭合描边或
    平行于剪影的环带
- `photo_echo` 几何门禁：mask 必须覆盖画布周长的 25% 以上（真正的满幅出血）；
  贴在画布边缘上的边界段豁免直线检测，而内部撕缝必须通过全部有机门禁
  （无直线 / 近直线长段、无规则锯齿、有真实变化），且计划声明的
  `seam.side` 必须是内部边界
- 结构化 `fusion`（融合）计划：AI 必须说明过渡颜色来自哪里、过渡接在哪些
  局部、材质如何连续——而不仅仅是避开禁止的伪影
- 结构化 `atmosphere`（氛围）计划（编辑拼贴设计层，改编自
  [gathered-scenes-zine by @Zeejay0](https://github.com/Zeejay0/gathered-scenes-zine-skill)）：
  单一插画语法、强制的 `photo_echo_subjects`（插画层必须重绘照片中的具体
  元素——与照片无关的通用涂鸦会被拒绝）、真实的插画场域占比、有张力的留白
  加强制的 `quiet_texture`（留白是水彩渍 / 网点颗粒 / 纸纤维，绝不是空白
  纸面）、绘制在受保护像素之外的撕纸纤维边缘、恰好一种结构性高饱和色，
  以及可选的一行安静微型文字（micro-text）
- 两阶段 AI 生成（先背景，再分离式过渡），最后是 AI 完全不参与的程序化恢复阶段
- 计划 / 清单交叉校验：恢复阶段可以验证 manifest 执行的正是预检通过的
  计划（`--plan`）
- 证据式视觉复检：`visual_review.py` 渲染复检人必须查看的缩略图，并校验
  `final-visual-review.json`。`fail` 是合法结论，会触发仅重新生成 Stage B
  过渡层
- 校验报告中的完整来源追踪：受保护像素、源文件、mask 文件、计划文件和生成
  prompt 的 SHA-256，以及源图 / mask / 画布尺寸和源图裁剪区域
- `run_compositor.py`：统一执行器（预检 -> 恢复 -> 缩略图 -> 复检校验），
  在 `pipeline-status.json` 中记录每个阶段的状态
- `smooth_mask.py` 辅助工具：对轮廓多边形做 Chaikin 切角平滑，或对粗糙
  mask 做模糊平滑
- 依赖极少：Python 3 + `numpy` + `Pillow`。不联网、无 API key、无机器
  特定路径

## 仓库结构

```
pixel-safe-image-compositor/
├── SKILL.md                        # skill 精简核心：工作流 + 硬规则
├── README.md
├── references/                     # agent 按需加载的详细参考
│   ├── plan-schema.md              # composition-plan.json 完整 schema 与示例
│   ├── geometry-gates.md           # 各模式 mask 几何门禁细则
│   ├── generation-guide.md         # Stage A/B 指南与逐字 prompt 禁令
│   └── scripts.md                  # 脚本详细文档与复检 schema
├── agents/
│   └── openai.yaml                 # Codex agent 元数据
├── scripts/
│   ├── run_compositor.py           # 统一流水线执行器
│   ├── smooth_mask.py              # Chaikin / 模糊 mask 平滑工具
│   ├── preflight_composition.py    # 生成前校验计划 + mask
│   ├── restore_and_verify.py       # 生成后贴回 + SHA-256 校验
│   └── visual_review.py            # 证据缩略图 + 复检校验
├── tests/
│   └── test_pipeline.py            # 端到端 + 单元测试
├── requirements.txt
├── .gitignore
└── LICENSE                         # MIT
```

## 安装

### 推荐：把下面这段话直接发给你的 Agent

无需手动操作，把这段 prompt 复制给 Codex / Claude Code / Cursor 等任意
coding agent，让它自己完成安装和验证：

```text
帮我安装一个 skill，仓库地址：
https://github.com/MBR000/pixel-safe-image-compositor

步骤：
1. 克隆仓库；
2. 把整个 pixel-safe-image-compositor 目录复制到你的 skills 目录
   （例如 ~/.codex/skills/ 或你所在环境的对应目录）；
3. 安装依赖：pip install -r requirements.txt（必要时用 venv）；
4. 在安装目录里运行 python -m unittest discover -s tests，确认全部通过。

完成后告诉我：安装路径、skill 名称、测试结果。
```

### 手动安装

将本目录克隆或复制到你的 agent skills 目录，例如：

```bash
git clone https://github.com/MBR000/pixel-safe-image-compositor.git
cp -r pixel-safe-image-compositor <your-skills-dir>/
```

当合成任务匹配时，agent 会自动加载 `SKILL.md`。

### 脚本依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 视觉 AI 撰写计划

AI 输出 `composition-plan.json`，描述 `focal_group`、`eye_path`、
`keep_context` / `drop_context`、候选形状、放置位置、`edge_profile`、
过渡计划、结构化 `fusion` 计划（色彩来源线索、过渡锚点、材质连续性、
密度梯度）、结构化 `atmosphere` 计划（插画语法、插画层要重绘的具体
`photo_echo_subjects`、场域与留白占比、`quiet_texture`、撕纸边缘处理、
单一结构性色彩强调、可选微型文字）、`preview_review_requirements`
承诺项，以及——在 `photo_echo` 模式下——把撕缝锚定到照片内容线的
`seam` 声明。完整 schema 见 `references/plan-schema.md`。

### 2. 构建并平滑 mask

```bash
python scripts/smooth_mask.py --polygon points.json --canvas 1024x1024 \
    --out mask.png --iterations 3
# 或平滑一张已有的粗糙 mask：
python scripts/smooth_mask.py --mask rough-mask.png --out mask.png
```

mask 必须是二值的（0/255）；预检会对抗锯齿 mask 发出警告。

### 3. 预检计划和 mask

```bash
python scripts/preflight_composition.py \
    --plan composition-plan.json \
    --mask mask.png \
    --out composition.preflight.json \
    --mask-preview mask-preview.png \
    --source source.png
```

退出码 1 表示必须先修正计划或 mask，再进行任何生成。矩形 mask 会被拒绝，
除非计划显式声明 `mode: photo_window` 且 `window.type: rectangle_mask`
（并且声明为 `photo_window` 的 mask 必须真的是矩形）。`photo_echo` 的
mask 必须真正满幅出血且内部撕缝为有机曲线。加上 `--source` 后，mask
预览图会在受保护区域内显示真实的源图内容。

### 4. AI 生成（两个阶段）

- Stage A：仅纸面、插画场域、背景。插画必须重绘计划中的
  `photo_echo_subjects`；`photo_echo` 模式下场景要跨缝延续；留白区域
  按计划的 `quiet_texture` 铺设材质
- Stage B：受保护区域之外的分离式、局部开放的过渡形状

每个 prompt 都必须禁止：重绘受保护区域、新增人物或动物、贴纸描边、
连续勾线、均匀光晕、长直边、规则锯齿、平行于受保护轮廓的描摹、
全图滤镜、AI 生成的文字、与照片无关的插画内容，以及空白无材质的留白。

### 5. 恢复并校验

```bash
python scripts/restore_and_verify.py \
    --ai-base final_ai_base.png \
    --manifest manifest.json \
    --plan composition-plan.json \
    --out final.png \
    --report final.verification.json
```

manifest 固定 RGBA 源抠图、其严格整数的放置坐标，以及
`alpha_policy: "nontransparent"`（可选加入 `mask` 和 `generation_prompt`
用于来源哈希追踪）。加上 `--plan` 后，manifest 的放置和模式必须与预检
通过的计划一致。脚本精确贴回非透明源像素，写出 `final.png`，重新读取，
再比对受保护像素的 SHA-256。任何不匹配：`verified=false`、非零退出。
IO 失败同样会写出 `verified=false` 报告。

### 6. 带证据的视觉复检

```bash
python scripts/visual_review.py --final final.png \
    --thumbnail final.thumbnail.png
# 查看两张图片，填写 final-visual-review.json，然后：
python scripts/visual_review.py --check final-visual-review.json
```

结论为 `"pass"` / `"fail"`，且 `fail` 是合法的——它以退出码 1 结束，
并指示只重新生成 Stage B 过渡层，绝不重新生成已校验的主体。

或者一次性执行所有程序化阶段：

```bash
python scripts/run_compositor.py --workdir out \
    --plan composition-plan.json --mask mask.png --source source.png \
    --manifest manifest.json --ai-base final_ai_base.png \
    --review final-visual-review.json
```

### 7. 交付物

- `composition-plan.json`
- `mask-preview.png`
- `final.png`
- `final.thumbnail.png`
- `composition.preflight.json`
- `final.verification.json`
- `final-visual-review.json`
- `pipeline-status.json`（使用统一执行器时）

所有图片输出均为 PNG。

## 验证

本 skill 附带对其保证的完整测试（40 个测试）：

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

覆盖内容：自由曲线 mask 通过预检；矩形、边缘抖动的"视觉矩形"、长直边、
浅斜线和规则锯齿在有机模式下被拒绝；`false` 检查项、无效 `fusion` 计划、
缺失的 `photo_echo_subjects` / `quiet_texture` 被拒绝；`photo_window`
接受矩形并拒绝有机 mask；`photo_echo` 接受带撕缝的满幅出血 mask，并拒绝
直线撕缝、悬浮形状和缺失的 seam / window 声明——同一张满幅 mask 在有机
模式下仍会失败；抗锯齿 mask 触发警告；源图叠加预览渲染正确；非整数放置
坐标被拒绝；恢复往返校验零像素不匹配；计划 / 清单交叉校验能捕捉分歧；
来源追踪字段（mask / prompt 哈希、尺寸、裁剪）被正确记录；IO 失败仍会
写出报告；视觉复检的 schema、pass 和 fail 路径行为正确；统一执行器端到端
通过、预检失败即停止、复检失败即失败；`smooth_mask.py` 两种模式都产出
改善几何形状的二值 mask。

## 安全性

这些脚本刻意设计为运行前易于审计：

- **不联网。** 全部代码中没有任何 socket / HTTP / API 相关的导入。
  不上传、不下载、不读取任何 API key。
- **不执行任意命令。** 没有 `eval`、`exec`、`os.system` 或 `shell=True`。
  唯一的 `subprocess` 调用在 `run_compositor.py` 里，只用固定参数调用
  本仓库内的同伴脚本。
- **纯文件进、文件出。** 每个脚本只读写你在命令行参数中显式指定的路径，
  不会触碰其他位置。
- **依赖极少。** 仅 Python 标准库加 `numpy` 和 `Pillow`。图片解析器
  偶有 CVE，请保持 Pillow 更新，并对不可信的输入图片保持常规谨慎。
- **代码量小，可完整人工审阅。** 五个脚本总计几百行。建议在运行之前
  （尤其是把上面"让 Agent 安装"的 prompt 发出去之前）先读一遍
  `scripts/` 目录。

## 致谢

`atmosphere` 设计层（撕纸纤维边缘、插画语法与场域纪律、结构性色彩强调、
微型文字系统）与 `photo_echo` 版式改编自 @Zeejay0 的
[gathered-scenes-zine-skill](https://github.com/Zeejay0/gathered-scenes-zine-skill)，
并重新设计为所有质感处理都保持在像素校验的受保护区域之外。

## 许可证

MIT——见 [LICENSE](LICENSE)。
