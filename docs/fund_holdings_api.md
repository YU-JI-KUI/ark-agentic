## 基金理财资产查询接口
### 请求接口
```python
import requests
import json

url = "http://test-host/v2/asset/inside/queryUserFundsAssetsList?userCode=1234&channel="

payload = json.dumps({
    "assetGrpType": 7, # 普通户：5，两融户：7 从context中获取的accountType进行对照并转换
    "appName": "AYLCAPP", # fixed value
    "limit": 20 # configrable value
})

headers = {
    'Content-Type': 'application/json',
    'validatedata': 'channel=REST&usercode=150573383&userid=12977997&account=3310123&branchno=3310&loginflag=3&mobileNo=137123123', # channel为固定值，其余字段从context中获取
    'signature': '/bzp123=' # 从context中获取
}

response = requests.request("POST", url, headers=headers, data=payload)
```
### 返回数据结构  
```json
{
    "results": {
        "total": 3,
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
            },
            {
                "statDate": 20260213,
                "secuCode": "158459",
                "secuName": "消费电子ETF",
                "marketType": "SZ",
                "price": "1.318",
                "holdCnt": "500",
                "mktVal": "42.80",
                "costPrice": "1.8850",
                "dayPft": "10.80",
                "dayPftRate": "0.0439",
                "holdPositionPft": "3.30",
                "holdPositionPftRate": "0.0175",
                "secuAcc": "0276525016",
                "exchangeType": "2",
                "position": 0.0000
            },
            {
                "statDate": 20260213,
                "secuCode": "159391",
                "secuName": "大盘价值ETF博时",
                "marketType": "SZ",
                "price": "1.012",
                "holdCnt": "300",
                "mktVal": "391.80",
                "costPrice": "1.8850",
                "dayPft": "11.80",
                "dayPftRate": "0.0439",
                "holdPositionPft": "3.30",
                "holdPositionPftRate": "0.0175",
                "secuAcc": "0276525016",
                "exchangeType": "2",
                "position": 0.0000
            }                        
        ],
        "accountType": 1,
        "dayTotalPftRate": -0.0512
    },
    "err": 0,
    "msg": "getUserAssetPftFromNtc_success",
    "status": 1
}
```

### 卡片字段映射
注意，ETF卡片中包含列表数据，对应的映射字段为`stock_list`，映射关系如下：
```json
{
    "total_market_value": "results.dayTotalMktVal", // ETF市值
    "total_profit": "results.dayTotalPft", // ETF今日收益
    "stock_list": {
        "list_mapping": "results.stockList", // ETF列表
        "field_mapping": {
            "code": "secuCode", // 证券代码
            "name": "secuName", // 证券名称
            "hold_cnt": "holdCnt", // 持仓数量
            "market_value": "mktVal", // 市值
            "day_profit": "dayPft", // 今日收益
            "day_profit_rate": "dayPftRate", // 今日收益率
        }
    }
}
```