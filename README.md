# 创业板 / 红利 ETF 比值看板

每日对比 **创业板ETF（159915）** 与 **红利ETF（510880）** 的价格比值，并给出相对高低估提示。

## 在线查看

部署完成后打开：

https://wangyule-0903.github.io/etf-ratio/

## 本地更新数据

```bash
pip install -r requirements.txt
python scripts/update_data.py
```

然后用浏览器打开 `docs/index.html`。

## 判断规则

比值 = 创业板ETF ÷ 红利ETF

| 历史分位 | 结论 |
|---|---|
| ≥ 80% | 创业板相对高估，红利相对低估 |
| ≤ 20% | 创业板相对低估，红利相对高估 |
| 中间 | 相对均衡 |

GitHub Actions 会在工作日自动更新 `docs/data.json`。

仅供学习研究，不构成投资建议。
