## 港股通资产查询接口
### 请求接口
```python
import requests
import json

url = "http://100.25.123.123/ais/v1/user/hksc/currentHold"

payload = json.dumps({
    "appName": "AYLCAPP", # fixed value
    "model": 1, # configrable value
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

### 卡片字段映射
```json
{
    "hold_market_value": "results.holdMktVal", // 持仓市值
    "day_total_profit": "results.dayTotalPft", // 今日收益
    "day_total_profit_rate": "results.dayTotalPftRate", // 今日收益率
    "available_hksc_share": "results.availableHkscShare", // 港股通可用额度
    "pre_frozen_asset": "results.preFrozenAsset", // 预冻结资产
}
```