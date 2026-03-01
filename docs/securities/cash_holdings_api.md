## 现金资产查询接口
### 请求接口
```python
import requests
import json

url = "http://test.host.cn:30060/assetservice/restapi/queryCashDetail"

payload = json.dumps({
    "channel": "native", # fixed value
    "appName": "AYLCAPP", # fixed value
    "tokenId": "N_TOKEN_STR", # token value from context
    "body": {
        "accountType": "1" # 1: 普通账户，2: 两融账户 from context
    }
})

headers = {
    'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)
```
### 返回数据结构  
```json
{
    "actionAuth": null,
    "status": 1,
    "errmsg": null,
    "requestid": "TMP_1652022052_1234567890",
    "results": {
        "accountType": "2",
        "rmb": {
            "cashBalance": "100015068.13",
            "available": "99846552.63",
            "avaliableDetail": {
                "drawBalance": "99846552.63",
                "hkStock": null,
                "cashBalanceDetail": {
                    "isSupportFastRedeem": "1",
                    "fundName": "现金宝",
                    "fundCode": "970172",
                    "dayProfit": "200.00", // 日收益
                    "accuProfit": "10000.00", // 累计收益
                }
            },
            "otdFundsTotal": null,
            "otdFundsDetail": null,
            "frozenFundsTotal": "168415.50",
            "frozenFundsDetail": [
                {
                    "name": "stockFreeze",
                    "value": "168415.50",
                    "chineseDesc": "股票交易冻结"
                }
            ],
            "inTransitAssetTotal": null,
            "inTransitAssetDetail": null
        }
    }
}
```

### 卡片字段映射
```json
{
    "cash_balance": "results.rmb.cashBalance", // 现金总额
    "cash_available": "results.rmb.available", // 可用资金
    "draw_balance": "results.rmb.avaliableDetail.drawBalance", // 可取资金
    "today_profit": "results.rmb.avaliableDetail.cashBalanceDetail.dayProfit" // 今日收益
}
```