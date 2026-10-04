# 上传 GitHub 与启用展示页

1. 解压 ZIP。进入 EquityResearchAgent 文件夹，将里面的文件上传到你自己的仓库根目录，不要再嵌套一层同名文件夹。
2. 先确认 .env.example 的密钥为空。不要上传你本机 .env、private 或 outputs。
3. 在仓库 Settings → Pages → Build and deployment 选择 Deploy from a branch，选择 main 分支和 /docs 文件夹，保存。
4. 等待 GitHub 完成部署；Pages 设置页会显示实际网址。仓库权限或账户方案可能影响 Pages 可用性。
5. README 的 docs/index.html 是源文件链接；部署后的正式页面从 Pages 设置页打开。ZIP 不预填不存在的仓库或网站地址。

报告在 docs/reports：NVDA（美股）、Tencent 00700（港股）、Moutai 600519（沪股），每家公司含 Word、PDF 和验证摘要。原始私人参考研报不在包内。

静态展示页可预览与下载已有报告，在线生成和 DeepSeek 讨论请在自己的电脑启动 Python 工作台。GitHub Pages 不运行这个 Python 后端，网页不收集或存放 API 密钥。

官方说明：[配置 GitHub Pages 发布目录](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。
