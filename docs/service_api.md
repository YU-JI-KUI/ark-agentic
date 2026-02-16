### 现金资产查询
```python
import requests
import json

url = "http://gm-yw-uat-001-k8s.paic.com.cn:30060/assetservice/restapi/queryCashDetail"

payload = json.dumps({
    "channel": "native",
    "appName": "AYLCAPP",
    "tokenId": "N_4ABD52CE290DD3850BC7742405EB7E327BBACDDD2C02847D257F8D14D925A334962DCA24CA5480E24E5812F67637DCCB5B982FF0EDA817936F4A1A2ECAD0096B9B1E6FA8941D",
    "body": {
        "accountType": "1"
    }
})

headers = {
    'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)
print(response.text)
```
## 总资产查询
``` python
url = "http://gm-yw-uat-001-k8s.paic.com.cn:30060/assetservice/restapi/getMyAllAssetsBy10"
# Payload 结构与上方类似，body 中 accountType 为 "2"
```

### 两融账户卡片映射关系
``` python
class MockSecuritiesDataServiceClient:
    @staticmethod
    def mock_margin_account_balance(user_id: str, query_date: str) -> dict:
        # 从 data/margin_acct.json 中读取模拟数据
        raw_data = MockSecuritiesDataServiceClient.load_mock_data_from_file("margin_acct.json")
        
        field_mapping = {
            "total_assets": "results.rmb.totalAssetVal",
            "net_assets": "results.rmb.rzrqAssetsInfo.netWorth",
            "total_liabilities": "results.rmb.rzrqAssetsInfo.totalLiabilities",
            "maintenance_margin_ratio": "results.rmb.rzrqAssetsInfo.mainRatio",
            "cash_balance": "results.rmb.cashBalance",
            "stock_market_value": "results.rmb.mktAssetsInfo.totalMktVal",
            "today_profit": "results.rmb.mktAssetsInfo.totalMktProfitToday",
            "today_return_rate": "results.rmb.mktAssetsInfo.totalMktYieldToday"
        }
        
        result = {}
        for tgt_field, src_path in field_mapping.items():
            value = MockSecuritiesDataServiceClient.get_nested_value(raw_data, src_path)
            result[tgt_field] = str(value) if value is not None else ""
        return result
```

#### 现金账户接口数据结构
```json
{
    "status": 1,
    "results": {
        "accountType": "2",
        "rmb": {
            "cashBalance": "100015068.13",
            "available": "99846552.63",
            "frozenFundsTotal": "168415.50",
            "frozenFundsDetail": [
                {
                    "name": "stockFreeze",
                    "value": "168415.50",
                    "chineseDesc": "股票交易冻结"
                }
            ]
        }
    }
}
```

#### 基金理财接口数据结构
```json
{
    "responseCode": "RSP_CODE_SUCCESS",
    "totalAssets": 150000.00,
    "userAssetList": [
        {
            "fundCode": "123456",
            "fundName": "平安稳健收益混合A",
            "holdingQty": 10000.00,
            "mktValue": 100000.00,
            "totalIncome": 1500.00,
            "holdProfitRate": 1.2
        }
    ]
}
```

#### 两融账户接口数据结构
```json
{
    "actionAuth": null,
    "status": 1,
    "errmsg": null,
    "requestId": "TMP_80a3bad9142c48d7a6e7b4fbc52d1bf8",
    "results": {
        "accountType": "2",
        "rmb": {
            "totalAssetVal": "333678978.13",
            "positions": "70.03%",
            "prudentPositions": "",
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
            "mktAssetsInfo": {
                "totalMktVal": "233663910.00",
                "totalMktProfitToday": "-1420880.00",
                "totalMktYieldToday": "-0.42",
                "stockText": "",
                "stockUrl": "",
                "stockNoticeId": ""
            },
            "fundMktAssetsInfo": null,
            "rzrqAssetsInfo": {
                "netWorth": "332733488.56",
                "totalLiabilities": "945497.57",
                "mainRatio": "35291.35"
            },
            "stockMktDetail": [
                /* 列表内容在截图中已折叠 */
            ],
            "fundMktDetail": null,
            "analyzeDataDetail": [
                /* 列表内容在截图中已折叠 */
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
                /* 列表已折叠 */
            ],
            "fundMktDetail": [
                /* 列表已折叠 */
            ],
            "analyzeDataDetail": [
                /* 列表已折叠 */
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

#### 资金账户总览
```json
{
    "results": {
        "accountType": "1",
        "rmb": {
            "totalAssetVal": "390664059.82",
            "positions": "23.16%",
            "cashGainAssetsInfo": {
                "cashBalance": "1227455354.88",
                "drawBalance": "3067362.75",
                "fundName": "开通现金宝+，实现白天炒股，晚上理财",
                "cashUrl": "http://www.pingan.com?Wt.mc_id=APP_251_247559_LC"
            },
            "mktAssetsInfo": {
                "totalMktVal": "267887813.40",
                "totalMktProfitToday": "-54638.28",
                "totalMktYieldToday": "-0.01"
            },
            "fundMktAssetsInfo": {
                "fundMktVal": "1323481.54",
                "finalDayProfit": "-1.32",
                "fundDateLine": "最新日收益 02月05日更新"
            },
            "rzrqAssetsInfo": null,
            "stockMktDetail": [], 
            "fundMktDetail": [],
            "analyzeDataDetail": []
        }
    },
    "status": 1
}
```
#### ETF资金账户（普通与两融一致）
```json
{
    "results": {
        "total": 4,
        "dayTotalMktVal": 514.90,
        "dayTotalPft": "-27.80",
        "stockList": [
            {
                "statDate": 20260213,
                "secuCode": "159958",
                "secuName": "创业板ETF工银",
                "marketType": "SZ",
                "price": "1.918",
                "holdCnt": "100",
                "mktVal": "191.80",
                "costPrice": "1.8850",
                "dayPft": "-8.80",
                "dayPftRate": "-0.0439",
                "holdPositionPft": "3.30",
                "holdPositionPftRate": "0.0175",
                "secuAcc": "0276525016",
                "exchangeType": "2",
                "position": 0.0000
            }
            // 列表后续还有 3 条数据已折叠
        ],
        "accountType": 1,
        "dayTotalPftRate": -0.0512
    },
    "err": 0,
    "msg": "getUserAssetPftFromNtc_success",
    "status": 1
}
```

#### 基金理财账户
```json
{
    "responseCode": "RSP_CODE_SUCCESS",
    "responseMsg": "查询成功",
    "totalAssets": 150000.00,
    "sumMktValue": 148000.00,
    "sumTotalIncome": 2000.00,
    "sumYesterdayIncome": 15.50,
    "userAssetList": [
        {
            "fundCode": "123456",
            "fundName": "平安稳健收益混合A",
            "holdingQty": 10000.00,
            "mktValue": 100000.00,
            "totalIncome": 1500.00,
            "yesterdayIncome": 10.00,
            "holdProfit": 1200.00,
            "holdProfitRate": 1.2,
            "category": "public",
            "pensionFlag": "N"
        }
    ]
}
```
#### 港股通数据结构
```json
{
    "err": 0,
    "errmsg": "success",
    "msg": "success",
    "status": 1,
    "results": {
        "progress": 0,
        "holdMktVal": 1000500.33,
        "holdPositionPft": 1000.22,
        "dayTotalPft": 100,
        "dayTotalPftRate": 0.03,
        "totalHkscShare": 10000,
        "availableHkscShare": 6000,
        "limitHkscShare": 4000,
        "preFrozenAsset": 6000.22,
        "stockList": [
            {
                "marketType": "HK",
                "mktVal": 0,
                "dayPft": 12.55,
                "dayPftRate": 0.1122,
                "holdPositionPft": 2.11,
                "holdPositionPftRate": 0.021,
                "position": "0.0000",
                "holdCnt": "2000",
                "shareBln": "1000",
                "price": "2.066",
                "costPrice": "1.9872",
                "secuCode": "10001",
                "secuName": "阿里巴巴",
                "secuAcc": "E022922565"
            }
        ],
        "preFrozenStockList": [
            {
                "secuName": "阿里巴巴",
                "secuCode": "10001",
                "preFrozenAsset": 6000.22
            }
        ]
    }
}
```

### 港股通接口
```python
import requests
import json

url = "http://10.25.163.161:80/ais/v1/user/hksc/currentHold"

payload = json.dumps({
    "model": 1,
    "limit": 3
})

headers = {
    'validatedata': 'channel=REST&usercode=150573383&userid=12977997&account=331019040951&branchno=3310&loginflag=3&mobileNo=13797781714',
    'signature': '/bZpTH76pZK1h2wu3m+9qVWvLag=',
    'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)
```
