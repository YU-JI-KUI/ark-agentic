## 用户股票盈亏排行（仅支持普通账户）

### 查询接口
``` python
url = "http://test-host/ais/getUserStkPftLoss"

payload = json.dumps(
{
    "timeType": 1, # 时间类型，非必填。1：本月， 3：今年， 4: 近一年， 5: 自定义时间区间（配合beginTime，endTime）， 13: 开户以来至今， 15: 本周
    "pftType": 1, # 1 - 查盈利排行， 2 - 查亏损排行
    "limit": 10,  # 查询条数，默认可以为10
    "stringParam": 1 # fixed-value
})
```
### 返回数据较多，仅提取以下有效信息
#### 仅支持普通账户
```json
{
    "results": {
        "pftCnt": "4", # 盈利股票个数
        "pftAmt": "13300", # 盈利合计
        "lossCnt": "6", # 亏损数量
        "lossAmt": "-9900", # 亏损合计
        "stockList": [
            {
                "stockName": "海特高新", # 股票名称
                "profit": "4000",  #收益额
                "profitRate": "0.0218", # 收益率
                "pftRatio": "0.211" # 收益占比
            }
        ],
        "status": 1, # 1 为正常返回
        "msg": "success",
        "errmsg": "success"
    }
}
```
