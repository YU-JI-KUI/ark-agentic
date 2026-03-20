## 用户资产历史信息

### 查询接口
``` python
url = "http://test-host/ais/getUserAssetPftCurve"

payload = json.dumps({
    "assetGrpType": 1,  # 1 普通账户， 2 两融账户
    "beginTime": 20240601, # 查询的起始时间
    "endTime": 20240614, # 结束时间
    "timeType": 1, # 时间类型，非必填。1：本月， 3：今年， 4: 近一年， 5: 自定义时间区间（配合beginTime，endTime）， 13: 开户以来至今， 15: 本周
    "stringParam": 1, # fixed-value
    "ruleType": 1 #fixed
})
```
### 返回数据较多，仅提取以下有效信息
#### 普通账户
```json
{
    "results": {
        "totalProfit": str, # 累计总收益
        "totalProfitRate": str, # 累计收益率
        "asset": [
            "100",   # 数组第一个为：期初总资产， 最后一个为：期末总资产
            "100.1",
            ...      
        ],
        "status": 1, # 1 为正常返回
        "msg": "success",
        "errmsg": "success"
    }
}
```

#### 两融账户
```json
{
    "results": {
        "totalProfit": "1299.3", # 累计总收益
        "totalProfitRate": "0.0023", # 累计收益率
        "asset": [
            "100",   # 数组第一个：期初净资产，最后一个：期末净资产
            "100.1",
            ...      
        ],
        "assetTotal": [
            "10000", # 数组第一个：期初总资产，最后一个：期末总资产
            "12000", 
            ...
        ],
        "status": 1, # 1 为正常返回
        "msg": "success",
        "errmsg": "success"
    }
}
```
