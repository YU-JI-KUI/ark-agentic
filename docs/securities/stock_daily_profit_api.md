## 用户股票每日收益明细（支持普通和两融）

### 查询接口
``` python
url = "http://test-host/ais/getUserGrpDayProfit"

payload = json.dumps(
{
    "assetGrpType": 1,  # 1 普通账户， 2 两融账户
    "beginTime": 20240601, # 查询的起始时间
    "endTime": 20240614, # 结束时间    
    "month": 202406,  # 查询指定月份，可代替用户输入起止日期
    "stringParam": 1 # fixed-value
})
```
### 返回数据较多，仅提取以下有效信息
```json
{
    "results": {
        "totalProfit": "100.9", # 总收益
        "totalProfitRate": "-0.234", # 总收益率
        "trdDate": [ # 交易日列表
            "20240603",
            "20240604",
            "20240605"
        ],
        "profitRate": [ # 与交易日对应的收益率
            "-0.0083",
            "休市",
            "-0.0122"
        ],
        "profit": [ # 与交易日对应的收益额
            "-28.08",
            "休市",
            "-32.01"
        ],
        "status": 1, # 1 为正常返回
        "msg": "success",
        "errmsg": "success"
    }
}
```
