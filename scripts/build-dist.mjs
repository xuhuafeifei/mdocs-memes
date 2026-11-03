#!/usr/bin/env node
/**
 * 把仓库里的产物打成一个「可发布」的 npm 包目录 dist/。
 *
 * 为什么需要 dist/：mdocs 的同步是「一次 npm install 拿整包，再原子覆盖系统库」，
 * 而 mdocs 按 meme_name 的纯文件名找图 —— 所以包根目录必须平铺：
 *
 *   dist/package.json   发布用清单（零依赖）
 *   dist/meme.json      图库索引
 *   dist/<id>.webp      每张图
 *
 * 源图（sheets/）、切图脚本（scripts/）、captions.json 都不进包。
 * 发布：npm run release（= build + npm publish ./dist）
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OUT = path.join(ROOT, "dist");
const INDEX = path.join(ROOT, "meme.json");
const MEMES = path.join(ROOT, "memes");
const ID_RE = /^[A-Za-z0-9_-]{1,32}$/;

function fail(message) {
  console.error("构建失败：" + message);
  process.exit(1);
}

function readRepoPackage() {
  const raw = fs.readFileSync(path.join(ROOT, "package.json"), "utf8");
  const pkg = JSON.parse(raw);
  if (!pkg.version) fail("根 package.json 缺 version");
  return pkg;
}

function readIndex() {
  if (!fs.existsSync(INDEX)) fail("缺少 meme.json（先跑 python3 scripts/slice.py）");
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(INDEX, "utf8"));
  } catch (err) {
    fail("meme.json 不是合法 JSON：" + err.message);
  }
  const list = Array.isArray(raw?.memes) ? raw.memes : [];
  if (list.length === 0) fail("meme.json 里没有 memes");

  const seenId = new Set();
  const seenFile = new Set();
  const entries = [];
  for (const item of list) {
    const id = typeof item?.id === "string" ? item.id.trim() : "";
    const desc = typeof item?.desc === "string" ? item.desc.trim() : "";
    const name = typeof item?.meme_name === "string" ? item.meme_name.trim() : "";
    if (!ID_RE.test(id)) fail("id 非法：" + JSON.stringify(item?.id));
    if (!desc) fail(id + " 缺 desc（Agent 只靠这句话选图）");
    // mdocs 侧只接受纯 basename，包内也必须平铺
    if (!name || name !== path.basename(name) || name.includes("\\")) {
      fail(id + " 的 meme_name 必须是纯文件名：" + JSON.stringify(name));
    }
    if (!/^[A-Za-z0-9_.-]+\.(webp|png|gif|jpe?g)$/i.test(name)) {
      fail(id + " 的图片扩展名不支持：" + name);
    }
    if (seenId.has(id)) fail("id 重复：" + id);
    if (seenFile.has(name)) fail("meme_name 重复：" + name);
    seenId.add(id);
    seenFile.add(name);
    entries.push({ id, desc, meme_name: name });
  }
  return { version: typeof raw.version === "number" ? raw.version : 1, memes: entries };
}

function copyFile(from, to, label) {
  const stat = fs.statSync(from);
  if (!stat.isFile() || stat.size === 0) fail(label + " 不存在或是空文件：" + from);
  fs.copyFileSync(from, to);
  return stat.size;
}

function main() {
  const repoPkg = readRepoPackage();
  const index = readIndex();

  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });

  let total = 0;
  for (const entry of index.memes) {
    const from = path.join(MEMES, entry.meme_name);
    if (!fs.existsSync(from)) fail("meme.json 指向的图片不存在：memes/" + entry.meme_name);
    total += copyFile(from, path.join(OUT, entry.meme_name), entry.meme_name);
  }
  copyFile(INDEX, path.join(OUT, "meme.json"), "meme.json");

  // 发布清单：务必零依赖 —— mdocs 那边是整包 npm install，带依赖会拖慢并扩大攻击面
  const publishPkg = {
    name: "mdocs-memes",
    version: repoPkg.version,
    description: "mdocs 系统表情包图库（meme.json + 图片，零依赖）",
    files: ["meme.json", "*.webp", "*.png", "*.gif", "*.jpg"],
    license: repoPkg.license ?? "MIT",
    dependencies: {},
  };
  fs.writeFileSync(path.join(OUT, "package.json"), JSON.stringify(publishPkg, null, 2) + "\n", "utf8");

  console.log("dist/ 就绪：v" + publishPkg.version + "，" + index.memes.length + " 张图，" + (total / 1024).toFixed(0) + " KB");
  console.log("发布：npm publish ./dist");
}

main();
