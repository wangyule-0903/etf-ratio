# 创业板 / 中证红利 指数比值看板

每日对比 **创业板指数（399006）** 与 **中证红利指数（000922）** 的点位比值，并给出相对高低估提示。

## 在线查看

https://wangyule-0903.github.io/etf-ratio/

## 本地更新数据

```bash
pip install -r requirements.txt
python scripts/update_data.py
```

然后用浏览器打开 `docs/index.html`。

## 判断规则

比值 = 创业板指数 ÷ 中证红利指数

| 历史分位 | 结论 |
|---|---|
| ≥ 80% | 创业板相对高估，中证红利相对低估 |
| ≤ 20% | 创业板相对低估，中证红利相对高估 |
| 中间 | 相对均衡 |

GitHub Actions 会在工作日北京时间约 **16:00–19:00** 多次自动尝试更新（降低漏跑概率）。也可在仓库 Actions 页面手动 Run workflow。

信号看指数；实盘可用对应 ETF 交易。仅供学习研究，不构成投资建议。
