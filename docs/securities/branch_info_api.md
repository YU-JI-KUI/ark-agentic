## 接口描述：开户营业部查询接口
### 请求信息
URL: http://host:1234/servicecenter/restapi/openWeb/getBranchInfo
HTTP方法: POST
HTTP头:
- validatedata: channel=REST&usercode=150573383&userid=12977997&account=331019040951&branchno=3310&loginflag=3&mobileNo=13797781714
- signature: /bZpTH76pZK1h2wu3m+9qVWvLag=

### 返回数据
```json
{
    "requestId": "69e66f2225544f04a0997c000389d757",
    "errMsg": "成功",
    "results": {
        "address": "深圳市罗湖笋岗梨园路 8号HALO广场4层, 邮编: 518000",
        "servicePhone": "营业部联系电话: 95547-8-9-2",   // 注意：这里原文是95511-8-9-2，但根据上下文可能是95547（平安证券客服），保留原样
        "branchName": "平安证券股份有限公司深圳红岭基金产业园证券营业部 (原深南中营业部)",
        "seatNo": {
            "sza": "007057",
            "sha": "43599"
        }
    },
    "status": 1
}
```