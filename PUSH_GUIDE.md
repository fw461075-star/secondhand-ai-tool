# 推送到 GitHub 操作指南

## 当前状态

- 本地仓库：`C:\Users\wff\产品\workbuddy\简历\GitHub-打包\secondhand-ai-tool-repo`
- 已本地提交：92 个文件（仅含二手信息聚合工具代码，已脱敏）
- 目标远程仓库：`https://github.com/fw461075-star/-.git`
- 需要你做：**把本地仓库推送到 GitHub**

---

## 第一步：准备 GitHub 访问令牌（Token）

GitHub 已不支持直接用密码登录。推送时需要输入 **Personal Access Token（PAT）**。

如果你还没有：

1. 打开 GitHub 网页 → 右上角头像 → **Settings**
2. 左侧最下方 → **Developer settings**
3. **Personal access tokens → Tokens (classic)**
4. 点击 **Generate new token (classic)**
5. Note 写：`push secondhand repo`
6. Expiration 选 `No expiration`（或 90 天）
7. 勾选 **`repo`** 这一项
8. 拉到最下点 **Generate token**
9. **立刻复制这串 token**（页面关闭后就看不到了）

---

## 第二步：在本地运行推送命令

打开 **Git Bash**（或任何 bash 终端），依次复制粘贴下面命令：

```bash
cd "C:/Users/wff/产品/workbuddy/简历/GitHub-打包/secondhand-ai-tool-repo"
git branch -M main
git remote add origin https://github.com/fw461075-star/-.git
git push -u origin main
```

执行到 `git push` 时会弹窗或终端提示输入：

- **Username**: `fw461075-star`
- **Password**: 粘贴你刚才复制的 **Token**（注意：不是 GitHub 登录密码！）

---

## 第三步：验证是否成功

推送成功后，刷新浏览器里的 `https://github.com/fw461075-star/-` 页面，应该能看到 92 个文件和 README。

---

## 如果仓库名不想叫 `-`

`-` 这个仓库名不太好看。你可以在 GitHub 仓库页 → **Settings** → **Repository name** 改成 `campus-secondhand-ai` 或 `secondhand-ai-tool`，改完名字后，本地不需要重新推，GitHub 会自动重定向。

但**改名前请确认先 push 成功一次**。

---

## 如果推送报错

| 报错 | 原因 | 解决 |
| --- | --- | --- |
| `remote: Repository not found` | 仓库名或用户名写错 | 检查 URL |
| `Authentication failed` | 用了密码而不是 Token | 换成 Token |
| `src refspec main does not match` | 本地分支名不对 | 先执行 `git branch -M main` |
| `failed to push some refs` | 远程仓库不为空 | 你在 GitHub 上初始化了 README/License，先删仓库重建空仓库，或用 `--force`（不建议新手用） |

---

## 推送后记得做的事

1. 把仓库访问链接加到简历里：`https://github.com/fw461075-star/-`
2. 如果仓库是**公开**的，任何人都能点开看；如果**私有**，面试时单独把链接发给面试官
3. 建议把仓库名从 `-` 改成 `secondhand-ai-tool` 或 `campus-secondhand-ai-tool`，更专业
