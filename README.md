# mdocs-memes

mdocs 智能助手的系统表情包图库：一张 3x3 大图切出 9 张，构建成 npm 包发布；mdocs 侧一次整包安装后原子覆盖。

    sheets/           源图（3x3 大图，一张 9 格）
      01-cute.png
      02-grumpy.png
      03-cheer.png
    captions.json     每格一条 { id, desc }，行优先 9 条
    scripts/slice.py  切片脚本（Python + Pillow）
    scripts/build-dist.mjs  打包脚本：校验 + 生成可发布的 dist/
    memes/            切图产物：单张 webp（去白边、抠白底、最长边 360）
    meme.json         图库索引
    dist/             发布包（平铺，npm 发布用，已 gitignore）

## 构建

    pip install pillow
    python3 scripts/slice.py      # sheets/ + captions.json → memes/ + meme.json
    npm run build                 # memes/ + meme.json → dist/

脚本做四件事：按每行的留白找切口（图不是严格三等分，相邻贴纸会溢出）→ 丢掉贴边碎块（邻格残留）
→ 按外接框裁紧 → 抠掉与外框连通的白色背景，存成 360px 的 webp。

## 发布（本仓库负责）

    npm version patch
    npm run release               # = npm run build && npm publish ./dist

发布的是 `dist/` 这个平铺包（`meme.json` + 27 张图 + 一份零依赖的 `package.json`），不是仓库根目录：

- **包根必须平铺**：mdocs 只按 `meme_name` 的纯文件名找图，不接受子目录；
- **必须零依赖**：mdocs 用 `npm install` 整包拉取并加 `--ignore-scripts`，带依赖会拖慢并扩大攻击面；
- 源图、切图脚本、captions 都不进包，只有图片和 `meme.json`。

发到 npmjs（淘宝镜像会自动同步，镜像不能直接发布）。要加速就把同步端的 registry 指到
`https://registry.npmmirror.com` —— 拉的是 tarball，不受 unpkg 白名单限制。

## 被 mdocs 采集（mdocs 负责）

mdocs 的系统库同步只需要一个包名：

    POST /api/memes/system/sync  { "spec": "mdocs-memes@latest" }

它做的事：`npm install <spec>` 到临时目录 → 只挑 `meme.json` 和清单里的图片 → 校验 → 原子覆盖
`<dataDir>/dsh-meme/`。整包一次往返，失败不动旧库。

meme.json 结构：

    { "version": 1,
      "memes": [{ "id": "deyi", "desc": "得意闭眼拳头…", "meme_name": "deyi.webp" }] }

- id 是助手在正文里输出的占位符 `[meme:deyi]`，前端拿它换图；改 id 会让旧消息失效
- desc 必填：Agent 不认识图片，全靠这句话判断什么时候用哪张
- meme_name 只允许纯文件名（不能带目录）

## 许可

- 代码（scripts/）：MIT，见 LICENSE
- 图片：AI 生成（作者自用），未声明商用许可
