## 总资产查询接口（含普通、两融）账户

### 查询接口
``` python
url = "http://gm-yw-uat-001-k8s.paic.com.cn:30060/assetservice/restapi/getMyAllAssetsBy10"

payload = json.dumps({
    "channel": "native",  # fixed value
    "appName": "AYLCAPP", # fixed value
    "tokenId":  "N_4ABD52CE290DD3850BC7742405EB7E327BBACDDD2C02847D257F8D14D925A334962DCA24CA5480E24E5812F67637DCCB5B982FF0EDA817936F4A1A2ECAD0096B9B1E6FA8941D", # token value from context.args
    "body": {
        "accountType": "1" # 1: 普通账户，2: 两融账户 from context.args
    }
})

headers = {
    'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)
```
### 返回数据结构    
#### 两融账户接口数据结构
```json5
{
    "actionAuth": null,
    // 返回状态码，1：成功，0：失败
    "status": 1,
    "errmsg": null,
    "requestId": "TMP_80a3bad9142c48d7a6e7b4fbc52d1bf8",
    // 结果数据
    "results": {
        // 账户类型，1：普通账户，2：两融账户
        "accountType": "2",
        "rmb": {
            "totalAssetVal": "333678978.13",
            "positions": "70.03%",
            "prudentPositions": "",
            // 现金资产
            "cashGainAssetsInfo": {
                "cashBalance": "100815068.13",
                "drawBalance": "99874458.88",
                "fundCode": "",
                "fundName": "",
                "cashYield": "",
                "cashText": "",
                "cashUrl": "",
                "cashNoticeId": ""
            },
            // 证券资产
            "mktAssetsInfo": {
                "totalMktVal": "233663910.00",
                "totalMktProfitToday": "-1420880.00",
                "totalMktYieldToday": "-0.42",
                "stockText": "",
                "stockUrl": "",
                "stockNoticeId": ""
            },
            // 基金资产
            "fundMktAssetsInfo": null,
            // 两融资产
            "rzrqAssetsInfo": {
                "netWorth": "332733488.56",
                "totalLiabilities": "945497.57",
                // 维持担保比例
                "mainRatio": "35291.35"
            },
            "stockMktDetail": null,
            "fundMktDetail": null,
            "analyzeDataDetail": [
                "key": "stock",
                "chineseDesc": "股票证券",
                "percent": "23.16",
                "list": [
                    {
                        "key": "Mkt_AG",
                        "chineseDesc": "A股",
                        "percent": "25.26",
                        "mktVal": "251400.40",
                    },
                    {
                        "key": "Mkt_GGT",
                        "chineseDesc": "港股通",
                        "percent": "11.77",
                        "mktVal": "103200.00",
                    },
                    {
                        "key": "Mkt_ETF",
                        "chineseDesc": "ETF",
                        "percent": "2.72",
                        "mktVal": "10000.00",
                    }
            ],
            "totalHoldingPmlUrl": null,
            "totalHolding": null,
            "totalHoldingUrl": null,
            "conservPos": null,
            "conservPosUrl": null,
            "aggPos": null,
            "aggPosUrl": null
        }
    }
}
```
#### 普通账户接口数据结构
```json
{
    "actionAuth": null,
    "status": 1,
    "errmsg": null,
    "requestId": "TMP_8a2a30df12dc4cd8a9a65dad3d6491e9",
    "results": {
        "accountType": "1",
        "rmb": {
            "totalAssetVal": "390664059.82",
            "positions": "23.16%",
            "prudentPositions": "",
            "cashGainAssetsInfo": {
                "cashBalance": "1227455354.88",
                "drawBalance": "3067362.75",
                "fundCode": "",
                "fundName": "开通现金宝+，实现白天炒股，晚上理财",
                "cashText": "购买现金产品，赚收益",
                "cashUrl": "http://www.pingan.com?Wt.mc_id=APP_251_247559_LC",
                "cashNoticeId": "247559"
            },
            "mktAssetsInfo": {
                "totalMktVal": "267887813.40",
                "totalMktProfitToday": "-54638.28",
                "totalMktYieldToday": "-0.01",
                "stockText": "",
                "stockUrl": "",
                "stockNoticeId": ""
            },
            "fundMktAssetsInfo": {
                "fundMktVal": "1323481.54",
                "finalDayProfit": "-1.32",
                "fundYieldToday": "",
                "fundDateLine": "最新日收益 02月05日更新",
                "fundMktText": "",
                "fundMktUrl": "",
                "fundMktSchemeUrl": "anlicaiapp://stock.pingan.com/webvns?url=https%3A%2F%2Fm.stg.pingan.com%2F... (已缩略)",
                "fundMktNoticeId": ""
            },
            "rzrqAssetsInfo": null,
            "stockMktDetail": [
                {
                    "key": "Mkt_AG",
                    "chineseDesc": "A股",
                    "mktVal": "267883.40",
                    "mktProfit": "-4638.28"
                },
                {
                    "key": "Mkt_GGT",
                    "chineseDesc": "港股通",
                    "mktVal": "265080.00",
                    "mktProfit": "-300.00"
                }
            ],
            "fundMktDetail": [
                "name": "jjMktTotal",
                "chineseDesc": "基金",
                "value": "3481.54",
                "lastDayProfit": "-1.32",
                "linkUrl": "http://m.pingan.com/webvns?url=https%3A%2F%2Fm.stg.pingan.com%2F... (已缩略)",
                "name": "yljMktTotal",
                "chineseDesc": "养老",
                "value": "3000.00",
                "lastDayProfit": "0.00",
                "linkUrl": "http://m.pingan.com/webvns?url=https%3A%2F%2Fm.stg.pingan.com%2F... (已缩略)",
            ],
            "analyzeDataDetail": [
                "key": "stock",
                "chineseDesc": "股票证券",
                "percent": "23.16",
                "list": [
                    {
                        "key": "Mkt_AG",
                        "chineseDesc": "A股",
                        "percent": "25.26",
                        "mktVal": "251400.40",
                    },
                    {
                        "key": "Mkt_GGT",
                        "chineseDesc": "港股通",
                        "percent": "11.77",
                        "mktVal": "103200.00",
                    },
                    {
                        "key": "Mkt_ETF",
                        "chineseDesc": "ETF",
                        "percent": "2.72",
                        "mktVal": "10000.00",
                    }
            ],
            "totalHoldingPmlUrl": null,
            "totalHolding": null,
            "totalHoldingUrl": null,
            "conservPos": null,
            "conservPosUrl": null
        }
    }
}
```

### 账户资产卡片字段映射关系
```json
{
    "total_assets": "results.rmb.totalAssetVal",
    "cash_balance": "results.rmb.cashBalance",
    "stock_market_value": "results.rmb.mktAssetsInfo.totalMktVal",
    "fund_market_value": "results.rmb.fundMktAssetsInfo.fundMktVal",
    "today_profit": "results.rmb.mktAssetsInfo.totalMktProfitToday",
    "today_return_rate": "results.rmb.mktAssetsInfo.totalMktYieldToday",
    // 以下为两融特有字段
    "net_assets": "results.rmb.rzrqAssetsInfo.netWorth",
    "total_liabilities": "results.rmb.rzrqAssetsInfo.totalLiabilities",
    "maintenance_margin_ratio": "results.rmb.rzrqAssetsInfo.mainRatio",
}
```
